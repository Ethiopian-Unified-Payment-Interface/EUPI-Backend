"""
Use Case: Consent & Pseudonymous Identity Service
Layer: 🟡 LAYER 2 — Application / Use Cases
Rule: Orchestrates logic via abstract ports only. NO HTTP calls, NO DB, NO FastAPI.

The single gate between developer applications and user data.

Every developer-facing read of user information goes through `build_claims`.
That is intentional: one function that can be read end to end, tested
exhaustively, and audited, rather than consent checks scattered across route
handlers where one omission silently leaks a field.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from backend.application.ports.consent_port import (
    ConsentRepositoryPort,
    FinVaultRepositoryPort,
    UserAppIdentityRepositoryPort,
)
from backend.application.ports.user_repository_port import UserRepositoryPort
from backend.application.ports.vault_port import IdentityVaultPort
from backend.config import settings
from backend.domain.models.consent import (
    Consent,
    ConsentScope,
    ConsentStatus,
    UserAppIdentity,
    VerifiedClaims,
)

logger = logging.getLogger(__name__)


class ConsentError(Exception):
    """Base exception for consent failures."""


class ConsentNotFoundError(ConsentError):
    """Raised when a grant referenced by ID does not exist."""


class RestrictedScopeError(ConsentError):
    """
    Raised when a restricted scope is requested through the self-service path.

    `identity:read:fin` cannot be granted this way — it needs an out-of-band
    licensing review, because handing a national ID to an application is not a
    decision a consent checkbox should be able to make on its own.
    """


class UnknownUserError(ConsentError):
    """Raised when a username has no corresponding account."""


class ConsentService:
    """
    Pseudonym allocation, consent lifecycle, and claim assembly.

    Injected dependencies (constructor injection / Dependency Inversion):
      - identity_repo: Per-app pseudonym persistence.
      - consent_repo:  Consent grant persistence.
      - vault_repo:    Encrypted FIN persistence.
      - vault:         Encryption and blind indexing.
      - user_repo:     Super App user lookup.
    """

    def __init__(
        self,
        identity_repo: UserAppIdentityRepositoryPort,
        consent_repo: ConsentRepositoryPort,
        vault_repo: FinVaultRepositoryPort,
        vault: IdentityVaultPort,
        user_repo: UserRepositoryPort,
    ) -> None:
        self._identity_repo = identity_repo
        self._consent_repo = consent_repo
        self._vault_repo = vault_repo
        self._vault = vault
        self._user_repo = user_repo

    # ── Pseudonyms ────────────────────────────────────────────────────────────

    def resolve_psu_id(self, username: str, app_id: str) -> str:
        """
        Return the stable pseudonym for a user within one application,
        allocating it on first contact.

        The value is 128 bits of randomness with no relationship to the user's
        identity or to the pseudonym the same person carries in any other
        application. Two developers comparing their entire user lists find no
        overlap, which is the property the whole design exists to provide.

        Args:
            username: Internal Super App handle.
            app_id:   Developer application.

        Returns:
            The `psu_id` for this pairing.
        """
        existing = self._identity_repo.get(username, app_id)
        if existing is not None:
            return existing.psu_id

        identity = UserAppIdentity(
            psu_id=f"psu_{secrets.token_hex(16)}",
            username=username,
            app_id=app_id,
            created_at=datetime.now(tz=timezone.utc),
        )
        self._identity_repo.create(identity)
        logger.info("Allocated pseudonym", extra={"app_id": app_id})
        return identity.psu_id

    def resolve_username(self, psu_id: str, app_id: str) -> str | None:
        """
        Resolve a pseudonym back to an internal username, for the owning app only.

        Args:
            psu_id: Pseudonym presented by the caller.
            app_id: The calling application.

        Returns:
            The internal username, or None if that pseudonym does not belong to
            this application.
        """
        identity = self._identity_repo.find_by_psu_id(psu_id, app_id)
        return identity.username if identity else None

    # ── Consent lifecycle ─────────────────────────────────────────────────────

    def grant(
        self,
        username: str,
        app_id: str,
        scope: ConsentScope,
        ttl_days: int | None = None,
        allow_restricted: bool = False,
    ) -> Consent:
        """
        Record a user's approval of one scope for one application.

        Args:
            username:         Internal Super App handle.
            app_id:           Developer application.
            scope:            Scope being granted.
            ttl_days:         Lifetime; defaults to CONSENT_DEFAULT_TTL_DAYS.
            allow_restricted: Permit a restricted scope. Set only by the admin
                              approval path after a licensing review, never by
                              the user-facing consent screen.

        Returns:
            The persisted grant.

        Raises:
            RestrictedScopeError: A restricted scope was requested without
                                  `allow_restricted`.
        """
        if scope.is_restricted and not allow_restricted:
            raise RestrictedScopeError(
                f"'{scope.value}' is a restricted scope and cannot be granted "
                f"through self-service consent. It requires an approved "
                f"licensing review."
            )

        days = ttl_days if ttl_days is not None else settings.CONSENT_DEFAULT_TTL_DAYS
        consent = Consent(
            consent_id=f"cns_{uuid.uuid4().hex[:20]}",
            username=username,
            app_id=app_id,
            scope=scope,
            status=ConsentStatus.GRANTED,
            granted_at=datetime.now(tz=timezone.utc),
            expires_at=datetime.now(tz=timezone.utc) + timedelta(days=days),
        )
        self._consent_repo.grant(consent)

        logger.info(
            "Consent granted",
            extra={"app_id": app_id, "scope": scope.value},
        )
        return consent

    def revoke(self, consent_id: str, username: str) -> None:
        """
        Revoke one grant.

        Args:
            consent_id: The grant to revoke.
            username:   The user requesting revocation. Verified against the
                        grant's owner so one user cannot revoke another's.

        Raises:
            ConsentNotFoundError: No such grant, or it belongs to someone else.
                                  Both produce the same error, so the response
                                  cannot be used to probe for other users' IDs.
        """
        all_grants = self._consent_repo.list_for_user(username)
        if not any(c.consent_id == consent_id for c in all_grants):
            raise ConsentNotFoundError(f"Consent '{consent_id}' not found.")

        self._consent_repo.revoke(consent_id)
        logger.info("Consent revoked", extra={"consent_id": consent_id})

    def disconnect_app(self, username: str, app_id: str) -> int:
        """
        Revoke every active grant a user has made to one application.

        Args:
            username: Internal Super App handle.
            app_id:   Application to disconnect.

        Returns:
            Number of grants revoked.
        """
        count = self._consent_repo.revoke_all_for_app(username, app_id)
        logger.info(
            "Application disconnected",
            extra={"app_id": app_id, "revoked": count},
        )
        return count

    def has_consent(self, username: str, app_id: str, scope: ConsentScope) -> bool:
        """
        Whether an application currently holds a live grant for one scope.

        Args:
            username: Internal Super App handle.
            app_id:   Developer application.
            scope:    Scope to check.

        Returns:
            True only if a grant exists, is not revoked, and has not expired.
        """
        consent = self._consent_repo.find(username, app_id, scope)
        return consent is not None and consent.is_active

    def list_user_consents(self, username: str) -> list[Consent]:
        """Every grant a user has made, for the consent screen."""
        return self._consent_repo.list_for_user(username)

    # ── FIN vault ─────────────────────────────────────────────────────────────

    def vault_fin(self, username: str, fin: str) -> None:
        """
        Encrypt and store a user's national ID.

        Args:
            username: Internal Super App handle.
            fin:      Plaintext Fayda Identification Number.
        """
        self._vault_repo.store(
            username=username,
            blind_index=self._vault.blind_index(fin),
            ciphertext=self._vault.encrypt(fin),
        )
        logger.info("FIN vaulted", extra={"username": username})

    def find_user_by_fin(self, fin: str) -> str | None:
        """
        Find an account by national ID without decrypting anything.

        Enforces "one account per national ID" via the blind index.

        Args:
            fin: Plaintext FIN to look up.

        Returns:
            The username, or None if no account exists.
        """
        return self._vault_repo.find_username_by_blind_index(self._vault.blind_index(fin))

    # ── Claim assembly ────────────────────────────────────────────────────────

    def build_claims(self, username: str, app_id: str) -> VerifiedClaims:
        """
        Assemble what one application is permitted to know about one user.

        This is the only path by which user data reaches a developer. Each
        optional field is populated strictly if its scope is currently granted,
        so a revoked or lapsed consent takes effect on the very next request
        rather than at the next token refresh.

        `psu_id`, verification status, and KYC level require no scope: they
        carry no personal data and an application already holding a valid token
        for this user necessarily knows the user exists.

        Args:
            username: Internal Super App handle.
            app_id:   Calling application.

        Returns:
            Claims containing only consented fields.

        Raises:
            UnknownUserError: No such user.
        """
        user = self._user_repo.get_by_username(username)
        if user is None:
            raise UnknownUserError(f"No user found for '{username}'.")

        claims = VerifiedClaims(
            psu_id=self.resolve_psu_id(username, app_id),
            identity_verified=True,  # Registration requires completed Fayda eKYC.
            kyc_level="STANDARD",
            phone_verified=True,     # Registration requires OTP to the Fayda phone.
        )

        if self.has_consent(username, app_id, ConsentScope.IDENTITY_READ_NAME):
            claims.full_name = user.full_name

        if self.has_consent(username, app_id, ConsentScope.IDENTITY_READ_PHONE):
            claims.phone_number = user.phone_number

        if self.has_consent(username, app_id, ConsentScope.IDENTITY_READ_FIN):
            # Restricted. Reaching here means a licensing review approved the
            # scope AND the user consented; the caller is expected to have
            # written an audit entry.
            ciphertext = self._vault_repo.get_ciphertext(username)
            if ciphertext is not None:
                claims.fin = self._vault.decrypt(ciphertext)
                logger.warning(
                    "Raw FIN released to an application under identity:read:fin",
                    extra={"app_id": app_id, "username": username},
                )

        return claims
