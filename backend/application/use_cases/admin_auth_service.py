"""
Use Case: Admin Authentication Service
Layer: 🟡 LAYER 2 — Application / Use Cases
Rule: Orchestrates logic via abstract ports only. NO HTTP calls, NO DB, NO FastAPI.

Replaces the previous "return an admin identity when no credentials are
supplied" behaviour. There is no unauthenticated path and no hardcoded token.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from backend.application.ports.admin_user_repository_port import AdminUserRepositoryPort
from backend.application.ports.password_hasher_port import PasswordHasherPort
from backend.domain.models.admin_user import AdminRole, AdminUser

logger = logging.getLogger(__name__)


class AdminAuthError(Exception):
    """Base exception for admin authentication failures."""


class InvalidAdminCredentialsError(AdminAuthError):
    """Raised when an email is unknown or a password does not match."""


class AdminAccountInactiveError(AdminAuthError):
    """Raised when a known operator's account has been disabled."""


class AdminAuthService:
    """
    Admin authentication and bootstrap orchestrator.

    Injected dependencies (constructor injection / Dependency Inversion):
      - admin_repo:      Persistence for operator accounts.
      - password_hasher: Hashing and verification of operator passwords.
    """

    def __init__(
        self,
        admin_repo: AdminUserRepositoryPort,
        password_hasher: PasswordHasherPort,
    ) -> None:
        self._admin_repo = admin_repo
        self._password_hasher = password_hasher

    def authenticate(self, email: str, password: str) -> AdminUser:
        """
        Verify operator credentials.

        Args:
            email:    Login email.
            password: Plaintext password.

        Returns:
            The authenticated :class:`~domain.models.admin_user.AdminUser`.

        Raises:
            InvalidAdminCredentialsError: Unknown email or wrong password.
            AdminAccountInactiveError:    Account exists but is disabled.
        """
        admin = self._admin_repo.get_by_email(email)

        if admin is None or admin.password_hash is None:
            # Hash a dummy value so a missing account and a wrong password take
            # comparable time — otherwise response latency enumerates valid emails.
            self._password_hasher.hash(password)
            logger.warning("Admin login failed: unknown email", extra={"email": email})
            raise InvalidAdminCredentialsError("Invalid email or password.")

        if not self._password_hasher.verify(password, admin.password_hash):
            logger.warning("Admin login failed: bad password", extra={"email": admin.email})
            raise InvalidAdminCredentialsError("Invalid email or password.")

        if not admin.is_active:
            logger.warning("Admin login refused: inactive account", extra={"email": admin.email})
            raise AdminAccountInactiveError("This admin account has been disabled.")

        if self._password_hasher.needs_rehash(admin.password_hash):
            self._admin_repo.update_password_hash(
                admin.email, self._password_hasher.hash(password)
            )

        self._admin_repo.update_last_login(admin.email, datetime.now(tz=timezone.utc))
        logger.info("Admin login succeeded", extra={"email": admin.email, "role": admin.role.value})

        return admin

    def bootstrap_first_admin(
        self,
        email: str,
        password: str,
        full_name: str = "Platform Administrator",
    ) -> AdminUser | None:
        """
        Create the initial ADMIN operator if no operators exist yet.

        Idempotent: does nothing once any operator is present, so it is safe to
        call on every startup. Without this there is no way to obtain the first
        credential, since there is no unauthenticated path into the Admin API.

        Args:
            email:     Login email for the first operator.
            password:  Plaintext password to hash and store.
            full_name: Display name.

        Returns:
            The created AdminUser, or None if operators already existed.
        """
        if self._admin_repo.count() > 0:
            return None

        admin = AdminUser(
            email=email.strip().lower(),
            full_name=full_name,
            role=AdminRole.ADMIN,
            is_active=True,
            created_at=datetime.now(tz=timezone.utc),
            password_hash=self._password_hasher.hash(password),
        )
        self._admin_repo.create(admin)
        logger.info("Bootstrapped first admin operator", extra={"email": admin.email})
        return admin
