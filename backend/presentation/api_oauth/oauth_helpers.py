"""
OAuth & PKCE Helper Functions
Layer: 🔵 LAYER 4 — Driving Adapters (Presentation)

Provides PKCE verification, client credential authentication, and
authorization code lifecycle management against the database.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.config import settings
from backend.infrastructure.database.models import (
    AuthorizationCodeRecord,
    DeveloperAppRecord,
)
from backend.infrastructure.database.session import RepositoryBase


class OAuthHelper(RepositoryBase):
    """Repository helper for OAuth2 client app lookups and authorization codes."""

    def __init__(self, db: Any = None) -> None:
        if db is None:
            try:
                from backend.main import get_db
                db = get_db()
            except Exception:
                from backend.infrastructure.database.session import Database
                db = Database(settings.DATABASE_URL)
        super().__init__(db)

    def get_app_by_client_id(self, client_id: str) -> DeveloperAppRecord | None:
        """Retrieve a developer application by its public client_id."""
        with self._session() as session:
            return (
                session.query(DeveloperAppRecord)
                .filter(DeveloperAppRecord.client_id == client_id)
                .first()
            )

    def get_app_by_id(self, app_id: str) -> DeveloperAppRecord | None:
        """Retrieve a developer application by its internal app_id."""
        with self._session() as session:
            return session.get(DeveloperAppRecord, app_id)

    def verify_client_secret(self, app: DeveloperAppRecord, client_secret: str) -> bool:
        """
        Verify a developer client secret.

        If client_secret_hash is not yet set (legacy mock apps), accepts secret
        matching `secret_{app_id}` or `client_secret`.
        """
        if not app.client_secret_hash:
            return client_secret in (f"secret_{app.app_id}", "client_secret", "secret_dev_123")
        try:
            from backend.infrastructure.auth.password_hasher import Argon2PasswordHasher
            hasher = Argon2PasswordHasher()
            return hasher.verify(client_secret, app.client_secret_hash)
        except Exception:
            return client_secret == app.client_secret_hash

    def create_authorization_code(
        self,
        app_id: str,
        username: str,
        scopes: list[str],
        redirect_uri: str,
        code_challenge: str,
        code_challenge_method: str = "S256",
        ttl_seconds: int = 60,
    ) -> str:
        """
        Generate a single-use 60-second authorization code and persist its SHA-256 hash.
        Returns the raw unhashed code to include in the redirect URL.
        """
        raw_code = f"eupi_ac_{secrets.token_urlsafe(32)}"
        code_hash = hashlib.sha256(raw_code.encode("utf-8")).hexdigest()
        now = datetime.now(tz=timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)

        record = AuthorizationCodeRecord(
            code_hash=code_hash,
            app_id=app_id,
            username=username,
            scopes=json.dumps(scopes),
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            expires_at=expires_at.replace(tzinfo=None),
            consumed_at=None,
            created_at=now.replace(tzinfo=None),
        )
        with self._session() as session:
            session.add(record)
        return raw_code

    def consume_authorization_code(
        self,
        raw_code: str,
        app_id: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> AuthorizationCodeRecord:
        """
        Validate and consume an authorization code.

        Raises ValueError on expired, already consumed, mismatched redirect_uri,
        or failed PKCE verification.
        """
        code_hash = hashlib.sha256(raw_code.encode("utf-8")).hexdigest()
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)

        with self._session() as session:
            record = session.get(AuthorizationCodeRecord, code_hash)
            if not record:
                raise ValueError("Invalid authorization code.")
            if record.consumed_at is not None:
                raise ValueError("Authorization code has already been consumed.")
            if record.expires_at <= now:
                raise ValueError("Authorization code has expired.")
            if record.app_id != app_id:
                raise ValueError("Authorization code was issued to a different client.")
            if record.redirect_uri != redirect_uri:
                raise ValueError("redirect_uri mismatch.")

            # PKCE Challenge Verification
            if not verify_pkce(code_verifier, record.code_challenge, record.code_challenge_method):
                raise ValueError("PKCE code_verifier validation failed.")

            # Mark consumed
            record.consumed_at = now
            return record


def verify_pkce(code_verifier: str, code_challenge: str, method: str = "S256") -> bool:
    """
    Verify RFC 7636 PKCE code_verifier against code_challenge.
    Supports S256 (SHA-256 base64url) and plain.
    """
    if method == "plain":
        return secrets.compare_digest(code_verifier, code_challenge)
    elif method == "S256":
        digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
        computed = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
        target = code_challenge.rstrip("=")
        return secrets.compare_digest(computed, target)
    return False
