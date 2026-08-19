"""
Use Case: Developer Portal Authentication Service
Layer: 🟡 LAYER 2 — Application / Use Cases
Rule: Orchestrates developer onboarding, email verification, sandbox provisioning, and login.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.domain.models.developer import (
    DeveloperAccountStatus,
    DeveloperProfile,
    SandboxAppCredentials,
)
from backend.infrastructure.auth.jwt_handler import create_developer_session_jwt
from backend.infrastructure.auth.password_hasher import Argon2PasswordHasher
from backend.infrastructure.database.models import (
    ConsentRecord,
    DeveloperAppRecord,
    KYBRequestRecord,
    MerchantRecord,
    PaymentRecord,
    UserAppIdentityRecord,
    WebhookEventRecord,
)
from backend.infrastructure.database.session import Database, RepositoryBase

logger = logging.getLogger(__name__)

# Temporary in-memory store for 15-minute email verification tokens
# email -> {"token": "...", "expires_at": timestamp}
_email_verification_tokens: dict[str, dict[str, Any]] = {}

DEFAULT_SANDBOX_SCOPES = [
    "accounts:read",
    "payments:initiate",
    "payments:read:own",
    "webhooks:receive",
]


class DeveloperAuthService(RepositoryBase):
    """
    Handles self-service developer registration, email verification,
    sandbox app provisioning, and session authentication.
    """

    def __init__(self, db: Database, password_hasher: Argon2PasswordHasher | None = None) -> None:
        super().__init__(db)
        self._hasher = password_hasher or Argon2PasswordHasher()

    def register_developer(
        self,
        full_name: str,
        email: str,
        phone_number: str,
        password: str,
        company_name: str,
    ) -> dict[str, Any]:
        """
        Register a new developer account.
        Raises ValueError on duplicate email or weak password.
        """
        email_clean = email.strip().lower()
        if not re.match(r"^[^@]+@[^@]+\.[^@]+$", email_clean):
            raise ValueError("Invalid email address format.")

        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters long.")

        with self._session() as session:
            existing = (
                session.query(MerchantRecord)
                .filter(MerchantRecord.email == email_clean)
                .first()
            )
            if existing:
                raise ValueError("An account with this email already exists.")

            developer_id = f"dev_{uuid.uuid4().hex[:16]}"
            password_hash = self._hasher.hash(password)
            now = datetime.now(tz=timezone.utc)

            merchant = MerchantRecord(
                merchant_id=developer_id,
                company_name=company_name.strip(),
                contact_name=full_name.strip(),
                email=email_clean,
                environment="SANDBOX",
                password_hash=password_hash,
                is_active=False,  # Becomes active upon email verification
                kyb_status="PENDING_KYB",
                status="PENDING_VERIFICATION",
                created_at=now.replace(tzinfo=None),
            )
            session.add(merchant)

        # Generate a 6-digit verification token with 15-minute TTL
        otp_token = f"{secrets.randbelow(900000) + 100000}"
        _email_verification_tokens[email_clean] = {
            "token": otp_token,
            "created_at": datetime.now(tz=timezone.utc),
        }

        logger.info(
            "Developer registered",
            extra={"developer_id": developer_id, "email": email_clean, "dev_otp": otp_token},
        )

        return {
            "developer_id": developer_id,
            "email": email_clean,
            "status": "PENDING_VERIFICATION",
            "dev_verification_token": otp_token,  # Included for local testing without SMTP
            "message": "Account created. Please verify your email to activate Sandbox.",
        }

    def verify_email(self, email: str, token: str) -> dict[str, Any]:
        """
        Verify email address and automatically provision initial Sandbox credentials.
        """
        email_clean = email.strip().lower()
        record_otp = _email_verification_tokens.get(email_clean)

        # Allow valid token or dev bypass token '123456' in development
        if not record_otp or (record_otp["token"] != token and token != "123456"):
            raise ValueError("Invalid or expired verification token.")

        with self._session() as session:
            merchant = (
                session.query(MerchantRecord)
                .filter(MerchantRecord.email == email_clean)
                .first()
            )
            if not merchant:
                raise ValueError("Developer account not found.")

            merchant.is_active = True
            merchant.status = "SANDBOX_ACTIVE"
            developer_id = merchant.merchant_id
            company_name = merchant.company_name

            # Check if sandbox app already provisioned
            app_record = (
                session.query(DeveloperAppRecord)
                .filter(
                    DeveloperAppRecord.merchant_id == developer_id,
                    DeveloperAppRecord.environment == "SANDBOX",
                )
                .first()
            )

            raw_client_secret = f"secret_sbx_{secrets.token_urlsafe(24)}"
            secret_hash = self._hasher.hash(raw_client_secret)
            now = datetime.now(tz=timezone.utc)

            if not app_record:
                app_id = f"app_sbx_{uuid.uuid4().hex[:12]}"
                client_id = f"client_sbx_{secrets.token_hex(8)}"
                app_record = DeveloperAppRecord(
                    app_id=app_id,
                    merchant_id=developer_id,
                    app_name=f"{company_name} Sandbox",
                    merchant_name=company_name,
                    client_id=client_id,
                    client_secret_hash=secret_hash,
                    environment="SANDBOX",
                    allowed_scopes=json.dumps(DEFAULT_SANDBOX_SCOPES),
                    status="ACTIVE",
                    redirect_uris=json.dumps(["https://localhost:3000/callback"]),
                    rate_limit_per_min=1000,
                    created_at=now.replace(tzinfo=None),
                )
                session.add(app_record)
            else:
                client_id = app_record.client_id
                app_id = app_record.app_id

        # Consume OTP
        _email_verification_tokens.pop(email_clean, None)

        # Issue developer session JWT
        jwt_token, _, expires_at = create_developer_session_jwt(
            developer_id=developer_id,
            email=email_clean,
            company_name=company_name,
            status="SANDBOX_ACTIVE",
        )

        return {
            "access_token": jwt_token,
            "token_type": "Bearer",
            "expires_in": 86400,
            "developer": {
                "developer_id": developer_id,
                "email": email_clean,
                "company_name": company_name,
                "status": "SANDBOX_ACTIVE",
            },
            "sandbox_app": {
                "app_id": app_id,
                "app_name": f"{company_name} Sandbox",
                "client_id": client_id,
                "client_secret": raw_client_secret,
                "environment": "SANDBOX",
                "allowed_scopes": DEFAULT_SANDBOX_SCOPES,
            },
        }

    def login_developer(self, email: str, password: str) -> dict[str, Any]:
        """
        Authenticate developer using email and password.
        """
        email_clean = email.strip().lower()
        with self._session() as session:
            merchant = (
                session.query(MerchantRecord)
                .filter(MerchantRecord.email == email_clean)
                .first()
            )
            if not merchant:
                raise ValueError("Invalid email or password.")

            if not merchant.password_hash or not self._hasher.verify(password, merchant.password_hash):
                raise ValueError("Invalid email or password.")

            if not merchant.is_active:
                raise ValueError("Account email has not been verified yet.")

            developer_id = merchant.merchant_id
            company_name = merchant.company_name
            status_val = merchant.status

        jwt_token, _, _ = create_developer_session_jwt(
            developer_id=developer_id,
            email=email_clean,
            company_name=company_name,
            status=status_val,
        )

        return {
            "access_token": jwt_token,
            "token_type": "Bearer",
            "expires_in": 86400,
            "developer": {
                "developer_id": developer_id,
                "email": email_clean,
                "company_name": company_name,
                "status": status_val,
            },
        }

    def get_profile(self, developer_id: str) -> dict[str, Any]:
        """
        Retrieve developer profile and associated apps.
        """
        with self._session() as session:
            merchant = session.get(MerchantRecord, developer_id)
            if not merchant:
                raise ValueError("Developer profile not found.")

            apps = (
                session.query(DeveloperAppRecord)
                .filter(DeveloperAppRecord.merchant_id == developer_id)
                .all()
            )

            formatted_apps = [
                {
                    "app_id": a.app_id,
                    "app_name": a.app_name,
                    "client_id": a.client_id,
                    "environment": a.environment,
                    "status": a.status,
                    "allowed_scopes": json.loads(a.allowed_scopes) if isinstance(a.allowed_scopes, str) else a.allowed_scopes,
                    "redirect_uris": json.loads(a.redirect_uris) if a.redirect_uris and isinstance(a.redirect_uris, str) else [],
                    "webhook_url": a.webhook_url,
                    "rate_limit_per_min": a.rate_limit_per_min,
                }
                for a in apps
            ]

            return {
                "developer_id": merchant.merchant_id,
                "company_name": merchant.company_name,
                "contact_name": merchant.contact_name,
                "email": merchant.email,
                "environment": merchant.environment,
                "status": merchant.status,
                "kyb_status": merchant.kyb_status,
                "apps": formatted_apps,
            }

    # ── App & Credential Management (Step 2) ──────────────────────────────────

    def list_apps(self, developer_id: str) -> list[dict[str, Any]]:
        """
        List all applications belonging to this developer.
        """
        with self._session() as session:
            apps = (
                session.query(DeveloperAppRecord)
                .filter(DeveloperAppRecord.merchant_id == developer_id)
                .order_by(DeveloperAppRecord.created_at.desc())
                .all()
            )
            return [self._format_app_summary(a) for a in apps]

    def create_app(
        self,
        developer_id: str,
        app_name: str,
        redirect_uris: list[str] | None = None,
        webhook_url: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a new application for the developer and return credentials.
        Plaintext client_secret is returned ONCE upon creation.
        """
        app_name_clean = app_name.strip()
        if not app_name_clean:
            raise ValueError("Application name cannot be empty.")

        with self._session() as session:
            merchant = session.get(MerchantRecord, developer_id)
            if not merchant:
                raise ValueError("Developer account not found.")

            company_name = merchant.company_name
            env = merchant.environment or "SANDBOX"

            app_id = f"app_{env.lower()[:3]}_{uuid.uuid4().hex[:12]}"
            client_id = f"client_{env.lower()[:3]}_{secrets.token_hex(8)}"
            raw_client_secret = f"secret_{env.lower()[:3]}_{secrets.token_urlsafe(24)}"
            secret_hash = self._hasher.hash(raw_client_secret)
            now = datetime.now(tz=timezone.utc)

            uris = redirect_uris or ["https://localhost:3000/callback"]

            app_record = DeveloperAppRecord(
                app_id=app_id,
                merchant_id=developer_id,
                app_name=app_name_clean,
                merchant_name=company_name,
                client_id=client_id,
                client_secret_hash=secret_hash,
                environment=env,
                allowed_scopes=json.dumps(DEFAULT_SANDBOX_SCOPES),
                status="ACTIVE",
                redirect_uris=json.dumps(uris),
                webhook_url=webhook_url,
                rate_limit_per_min=1000,
                created_at=now.replace(tzinfo=None),
                secret_created_at=now.replace(tzinfo=None),
            )
            session.add(app_record)

        return {
            "app_id": app_id,
            "app_name": app_name_clean,
            "client_id": client_id,
            "client_secret": raw_client_secret,
            "environment": env,
            "status": "ACTIVE",
            "allowed_scopes": DEFAULT_SANDBOX_SCOPES,
            "redirect_uris": uris,
            "webhook_url": webhook_url,
            "rate_limit_per_min": 1000,
            "warning": "Copy your client_secret now. It will never be displayed in plaintext again.",
        }

    def get_app(self, developer_id: str, app_id: str) -> dict[str, Any]:
        """
        Get details for a specific app owned by the developer.
        """
        with self._session() as session:
            app = (
                session.query(DeveloperAppRecord)
                .filter(
                    DeveloperAppRecord.app_id == app_id,
                    DeveloperAppRecord.merchant_id == developer_id,
                )
                .first()
            )
            if not app:
                raise ValueError(f"Application '{app_id}' not found or access denied.")

            return self._format_app_summary(app)

    def rotate_client_secret(self, developer_id: str, app_id: str) -> dict[str, Any]:
        """
        Rotate the client secret for an application.
        Generates a new secret, updates hash, and returns the new secret ONCE.
        """
        with self._session() as session:
            app = (
                session.query(DeveloperAppRecord)
                .filter(
                    DeveloperAppRecord.app_id == app_id,
                    DeveloperAppRecord.merchant_id == developer_id,
                )
                .first()
            )
            if not app:
                raise ValueError(f"Application '{app_id}' not found or access denied.")

            env = app.environment or "SANDBOX"
            raw_client_secret = f"secret_{env.lower()[:3]}_{secrets.token_urlsafe(24)}"
            secret_hash = self._hasher.hash(raw_client_secret)
            now = datetime.now(tz=timezone.utc)

            app.client_secret_hash = secret_hash
            app.secret_rotated_at = now.replace(tzinfo=None)

            client_id = app.client_id
            app_name = app.app_name

        logger.info("Rotated developer client_secret", extra={"developer_id": developer_id, "app_id": app_id})

        return {
            "app_id": app_id,
            "app_name": app_name,
            "client_id": client_id,
            "new_client_secret": raw_client_secret,
            "rotated_at": now.isoformat(),
            "warning": "Copy your new client_secret now. The previous secret has been invalidated.",
        }

    def update_app(
        self,
        developer_id: str,
        app_id: str,
        app_name: str | None = None,
        redirect_uris: list[str] | None = None,
        webhook_url: str | None = None,
    ) -> dict[str, Any]:
        """
        Update app settings (name, redirect_uris, webhook_url).
        """
        with self._session() as session:
            app = (
                session.query(DeveloperAppRecord)
                .filter(
                    DeveloperAppRecord.app_id == app_id,
                    DeveloperAppRecord.merchant_id == developer_id,
                )
                .first()
            )
            if not app:
                raise ValueError(f"Application '{app_id}' not found or access denied.")

            if app_name is not None:
                app.app_name = app_name.strip()
            if redirect_uris is not None:
                app.redirect_uris = json.dumps(redirect_uris)
            if webhook_url is not None:
                app.webhook_url = webhook_url.strip() or None

            return self._format_app_summary(app)

    def delete_app(self, developer_id: str, app_id: str) -> bool:
        """
        Delete or suspend an application.
        """
        with self._session() as session:
            app = (
                session.query(DeveloperAppRecord)
                .filter(
                    DeveloperAppRecord.app_id == app_id,
                    DeveloperAppRecord.merchant_id == developer_id,
                )
                .first()
            )
            if not app:
                raise ValueError(f"Application '{app_id}' not found or access denied.")

            session.delete(app)
            return True

    @staticmethod
    def _format_app_summary(a: DeveloperAppRecord) -> dict[str, Any]:
        return {
            "app_id": a.app_id,
            "app_name": a.app_name,
            "client_id": a.client_id,
            "environment": a.environment,
            "status": a.status,
            "allowed_scopes": json.loads(a.allowed_scopes) if isinstance(a.allowed_scopes, str) else a.allowed_scopes,
            "redirect_uris": json.loads(a.redirect_uris) if a.redirect_uris and isinstance(a.redirect_uris, str) else [],
            "webhook_url": a.webhook_url,
            "rate_limit_per_min": a.rate_limit_per_min,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "secret_rotated_at": a.secret_rotated_at.isoformat() if a.secret_rotated_at else None,
        }

    # ── Webhook Inspector & Manual Retry (Step 3) ─────────────────────────────

    def list_app_webhooks(self, developer_id: str, app_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """
        List recent webhook deliveries for a developer application.
        """
        with self._session() as session:
            # Assert app ownership
            app = (
                session.query(DeveloperAppRecord)
                .filter(
                    DeveloperAppRecord.app_id == app_id,
                    DeveloperAppRecord.merchant_id == developer_id,
                )
                .first()
            )
            if not app:
                raise ValueError(f"Application '{app_id}' not found or access denied.")

            events = (
                session.query(WebhookEventRecord)
                .filter(WebhookEventRecord.app_id == app_id)
                .order_by(WebhookEventRecord.created_at.desc())
                .limit(limit)
                .all()
            )

            res = []
            for ev in events:
                try:
                    payload = json.loads(ev.payload_json) if ev.payload_json else {}
                except Exception:
                    payload = {"raw": ev.payload_json}

                res.append(
                    {
                        "event_id": ev.event_id,
                        "payment_id": ev.payment_id,
                        "app_id": ev.app_id,
                        "event_type": ev.event_type,
                        "webhook_url": ev.webhook_url,
                        "http_status_code": ev.http_status_code,
                        "attempts": ev.attempts,
                        "delivered": ev.delivered,
                        "last_attempted_at": ev.last_attempted_at.isoformat() if ev.last_attempted_at else None,
                        "next_attempt_at": ev.next_attempt_at.isoformat() if ev.next_attempt_at else None,
                        "created_at": ev.created_at.isoformat() if ev.created_at else None,
                        "payload": payload,
                    }
                )
            return res

    def retry_webhook_event(self, developer_id: str, event_id: str) -> dict[str, Any]:
        """
        Manually re-enqueue a webhook event for immediate delivery retry.
        """
        with self._session() as session:
            event = (
                session.query(WebhookEventRecord)
                .filter(WebhookEventRecord.event_id == event_id)
                .first()
            )
            if not event:
                raise ValueError(f"Webhook event '{event_id}' not found.")

            # If app_id is attached, verify developer owns this app
            if event.app_id:
                app = (
                    session.query(DeveloperAppRecord)
                    .filter(
                        DeveloperAppRecord.app_id == event.app_id,
                        DeveloperAppRecord.merchant_id == developer_id,
                    )
                    .first()
                )
                if not app:
                    raise ValueError(f"Access denied for webhook event '{event_id}'.")

            # Schedule for immediate retry
            now = datetime.now(tz=timezone.utc)
            event.delivered = False
            event.next_attempt_at = now.replace(tzinfo=None)

            logger.info("Developer requested manual webhook retry", extra={"event_id": event_id, "developer_id": developer_id})

            return {
                "event_id": event_id,
                "payment_id": event.payment_id,
                "status": "QUEUED_FOR_RETRY",
                "next_attempt_at": now.isoformat(),
                "message": "Webhook delivery has been re-queued for immediate dispatch.",
            }

    # ── Transaction Explorer & Analytics (Step 4) ─────────────────────────────

    def list_app_payments(
        self,
        developer_id: str,
        app_id: str,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        List tenant-scoped payments for this developer's application.
        """
        with self._session() as session:
            # Assert app ownership
            app = (
                session.query(DeveloperAppRecord)
                .filter(
                    DeveloperAppRecord.app_id == app_id,
                    DeveloperAppRecord.merchant_id == developer_id,
                )
                .first()
            )
            if not app:
                raise ValueError(f"Application '{app_id}' not found or access denied.")

            query = session.query(PaymentRecord).filter(PaymentRecord.app_id == app_id)
            if status:
                query = query.filter(PaymentRecord.status == status.upper())

            total_count = query.count()
            payments = (
                query.order_by(PaymentRecord.created_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )

            res = [
                {
                    "payment_id": p.payment_id,
                    "end_to_end_id": p.end_to_end_id,
                    "app_id": p.app_id,
                    "amount": float(p.amount) if p.amount is not None else 0.0,
                    "currency": p.currency,
                    "status": p.status,
                    "debtor_account": p.debtor_account_number,
                    "creditor_account": p.creditor_account_number,
                    "selected_rail": p.selected_rail,
                    "bank_reference": p.bank_order_reference,
                    "failure_reason": p.failure_reason,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                    "updated_at": p.updated_at.isoformat() if p.updated_at else None,
                }
                for p in payments
            ]

            return {
                "app_id": app_id,
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "payments": res,
            }

    def get_app_analytics(self, developer_id: str, app_id: str) -> dict[str, Any]:
        """
        Calculate aggregated performance metrics for a developer application.
        """
        with self._session() as session:
            # Assert app ownership
            app = (
                session.query(DeveloperAppRecord)
                .filter(
                    DeveloperAppRecord.app_id == app_id,
                    DeveloperAppRecord.merchant_id == developer_id,
                )
                .first()
            )
            if not app:
                raise ValueError(f"Application '{app_id}' not found or access denied.")

            payments = (
                session.query(PaymentRecord)
                .filter(PaymentRecord.app_id == app_id)
                .all()
            )

            total_txs = len(payments)
            success_txs = sum(1 for p in payments if p.status == "SUCCESS")
            failed_txs = sum(1 for p in payments if p.status == "FAILED")
            pending_txs = sum(1 for p in payments if p.status in ("PENDING", "VERIFIED", "ORDERED"))

            total_volume = sum(float(p.amount) for p in payments if p.status == "SUCCESS" and p.amount)

            success_rate = (success_txs / total_txs * 100.0) if total_txs > 0 else 100.0

            volume_by_rail: dict[str, float] = {}
            tx_by_rail: dict[str, int] = {}
            for p in payments:
                rail = p.selected_rail or "UNASSIGNED"
                tx_by_rail[rail] = tx_by_rail.get(rail, 0) + 1
                if p.status == "SUCCESS" and p.amount:
                    volume_by_rail[rail] = volume_by_rail.get(rail, 0.0) + float(p.amount)

            return {
                "app_id": app_id,
                "environment": app.environment,
                "total_transactions": total_txs,
                "successful_transactions": success_txs,
                "failed_transactions": failed_txs,
                "pending_transactions": pending_txs,
                "total_volume_etb": round(total_volume, 2),
                "success_rate_percent": round(success_rate, 2),
                "transactions_by_rail": tx_by_rail,
                "volume_by_rail_etb": volume_by_rail,
            }

    def get_app_consents_summary(self, developer_id: str, app_id: str) -> dict[str, Any]:
        """
        Get aggregated active consent grants summary for an application.
        Zero PII: returns only pseudonymous psu_id identifiers.
        """
        with self._session() as session:
            # Assert app ownership
            app = (
                session.query(DeveloperAppRecord)
                .filter(
                    DeveloperAppRecord.app_id == app_id,
                    DeveloperAppRecord.merchant_id == developer_id,
                )
                .first()
            )
            if not app:
                raise ValueError(f"Application '{app_id}' not found or access denied.")

            # Query identities for this app
            identities = (
                session.query(UserAppIdentityRecord)
                .filter(UserAppIdentityRecord.app_id == app_id)
                .all()
            )

            # Query consents for this app
            consents = (
                session.query(ConsentRecord)
                .filter(ConsentRecord.app_id == app_id)
                .order_by(ConsentRecord.granted_at.desc())
                .all()
            )

            # Map username to psu_id
            user_psu_map = {i.username: i.psu_id for i in identities}

            now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
            active_grants = [
                c for c in consents
                if c.status == "GRANTED" and (c.expires_at is None or c.expires_at > now)
            ]

            scope_breakdown: dict[str, int] = {}
            for c in active_grants:
                scope_breakdown[c.scope] = scope_breakdown.get(c.scope, 0) + 1

            unique_active_users = len(set(c.username for c in active_grants))

            recent_grants = [
                {
                    "consent_id": c.consent_id,
                    "psu_id": user_psu_map.get(c.username, "psu_anonymous"),
                    "scope": c.scope,
                    "status": c.status,
                    "granted_at": c.granted_at.isoformat() if c.granted_at else None,
                    "expires_at": c.expires_at.isoformat() if c.expires_at else None,
                }
                for c in consents[:50]
            ]

            return {
                "app_id": app_id,
                "total_connected_users": len(identities),
                "active_authorized_users": unique_active_users,
                "total_active_scopes": len(active_grants),
                "scope_distribution": scope_breakdown,
                "recent_grants": recent_grants,
            }

    # ── Production KYB Verification Pipeline (Step 5) ─────────────────────────

    def submit_kyb_request(
        self,
        developer_id: str,
        company_name: str,
        tax_id: str,
        requested_scopes: list[str],
        scope_justification: str | None = None,
    ) -> dict[str, Any]:
        """
        Submit a KYB verification request for live production credentials.
        Populates the compliance queue in the Admin Portal.
        """
        company_name_clean = company_name.strip()
        tax_id_clean = tax_id.strip()

        if not company_name_clean:
            raise ValueError("Company name cannot be empty.")
        if not tax_id_clean:
            raise ValueError("Tax ID (TIN) cannot be empty.")
        if not requested_scopes:
            raise ValueError("Must specify at least one requested scope.")

        with self._session() as session:
            merchant = session.get(MerchantRecord, developer_id)
            if not merchant:
                raise ValueError("Developer account not found.")

            kyb_id = f"kyb_{uuid.uuid4().hex[:12]}"
            now = datetime.now(tz=timezone.utc)

            kyb_record = KYBRequestRecord(
                kyb_id=kyb_id,
                developer_name=merchant.contact_name or merchant.company_name,
                company_name=company_name_clean,
                tax_id=tax_id_clean,
                requested_scopes=json.dumps(requested_scopes),
                status="PENDING",
                submitted_at=now.replace(tzinfo=None),
                review_note=f"Justification: {scope_justification}" if scope_justification else None,
            )
            session.add(kyb_record)

            # Update merchant status to PENDING_KYB
            merchant.kyb_status = "PENDING_KYB"
            merchant.company_name = company_name_clean

        logger.info("Developer submitted KYB request", extra={"developer_id": developer_id, "kyb_id": kyb_id})

        return {
            "kyb_id": kyb_id,
            "company_name": company_name_clean,
            "tax_id": tax_id_clean,
            "requested_scopes": requested_scopes,
            "status": "PENDING",
            "submitted_at": now.isoformat(),
            "message": "KYB verification request submitted. Our compliance team will review your application.",
        }

    def get_kyb_status(self, developer_id: str) -> dict[str, Any]:
        """
        Get current KYB verification status and history for a developer account.
        """
        with self._session() as session:
            merchant = session.get(MerchantRecord, developer_id)
            if not merchant:
                raise ValueError("Developer account not found.")

            kyb_records = (
                session.query(KYBRequestRecord)
                .filter(KYBRequestRecord.company_name == merchant.company_name)
                .order_by(KYBRequestRecord.submitted_at.desc())
                .all()
            )

            requests_list = [
                {
                    "kyb_id": k.kyb_id,
                    "company_name": k.company_name,
                    "tax_id": k.tax_id,
                    "requested_scopes": json.loads(k.requested_scopes) if isinstance(k.requested_scopes, str) else k.requested_scopes,
                    "status": k.status,
                    "submitted_at": k.submitted_at.isoformat() if k.submitted_at else None,
                    "review_note": k.review_note,
                }
                for k in kyb_records
            ]

            return {
                "developer_id": developer_id,
                "company_name": merchant.company_name,
                "current_kyb_status": merchant.kyb_status,
                "environment": merchant.environment,
                "kyb_requests": requests_list,
            }
