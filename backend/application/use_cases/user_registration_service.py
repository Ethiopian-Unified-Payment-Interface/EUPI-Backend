"""
Use Case: User Registration Service
Layer: 🟡 LAYER 2 — Application / Use Cases
Rule: Orchestrates logic via abstract ports only. NO HTTP calls, NO DB, NO FastAPI.

Responsibilities:
  - Register a new super app user after successful Fayda eKYC verification.
  - Validate username uniqueness and format constraints.
  - Ensure no duplicate registration for the same FIN.
  - Return a fully populated SuperAppUser domain object.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone

# Domain imports only
from backend.domain.models.user import PublicUserProfile, SuperAppUser

# Application-layer port contracts only — never concrete adapters
from backend.application.ports.user_repository_port import UserRepositoryPort

logger = logging.getLogger(__name__)

# Username constraints
_USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_]{3,30}$")


class UserRegistrationService:
    """
    User Registration Use-Case Orchestrator.

    Injected dependencies (constructor injection / Dependency Inversion):
      - user_repo: A UserRepositoryPort for persisting user accounts.
    """

    def __init__(self, user_repo: UserRepositoryPort) -> None:
        self._user_repo = user_repo

    @staticmethod
    def _hash_pin(pin: str) -> str:
        """Hash a 6-digit PIN with SHA-256. Never store plaintext PINs."""
        return hashlib.sha256(pin.encode()).hexdigest()

    def register_user(
        self,
        username: str,
        fin: str,
        full_name: str,
        phone_number: str,
        pin: str,
    ) -> SuperAppUser:
        """
        Register a new super app user.

        The caller (presentation layer) must have already verified the FIN
        via the Fayda eKYC flow before calling this method.

        Args:
            username:     Unique handle (3-30 chars, alphanumeric + underscores).
            fin:          14-digit Fayda Identification Number.
            full_name:    Legal name from Fayda registry.
            phone_number: E.164 phone number.

        Returns:
            A fully populated SuperAppUser domain object.

        Raises:
            InvalidUsernameError: If username doesn't match format constraints.
            UsernameAlreadyTakenError: If username is already registered.
            FINAlreadyRegisteredError: If FIN is already linked to an account.
        """
        # Validate username format
        if not _USERNAME_PATTERN.match(username):
            raise InvalidUsernameError(
                f"Username '{username}' is invalid. Must be 3-30 characters, "
                "alphanumeric and underscores only."
            )

        # Check username uniqueness
        if self._user_repo.username_exists(username):
            raise UsernameAlreadyTakenError(
                f"Username '{username}' is already taken."
            )

        # Check FIN uniqueness (one account per national ID)
        existing = self._user_repo.get_by_fin(fin)
        if existing is not None:
            raise FINAlreadyRegisteredError(
                f"A super app account already exists for this FIN."
            )

        # Validate PIN format
        if not pin.isdigit() or len(pin) != 6:
            raise InvalidPINError(
                "PIN must be exactly 6 digits."
            )

        user = SuperAppUser(
            user_id=str(uuid.uuid4()),
            username=username,
            fin=fin,
            full_name=full_name,
            phone_number=phone_number,
            pin_hash=self._hash_pin(pin),
            created_at=datetime.now(tz=timezone.utc),
            is_active=True,
        )

        self._user_repo.create_user(user)

        logger.info(
            "Super app user registered",
            extra={"user_id": user.user_id, "username": user.username},
        )

        return user

    def get_public_profile(self, username: str) -> PublicUserProfile:
        """
        Look up a user's public profile by username.

        Used for P2P transfer recipient resolution — the sender types a
        username and sees the recipient's name before confirming.

        Args:
            username: The unique handle to look up.

        Returns:
            A PublicUserProfile containing only non-sensitive information.

        Raises:
            UserNotFoundError: If no user exists with this username.
        """
        user = self._user_repo.get_by_username(username)
        if user is None:
            raise UserNotFoundError(
                f"No user found with username '{username}'."
            )

        return PublicUserProfile(
            username=user.username,
            full_name=user.full_name,
        )

    def verify_pin(self, username: str, pin: str) -> SuperAppUser:
        """
        Verify a user's PIN for app login.

        Args:
            username: The unique handle of the user.
            pin:      The 6-digit PIN entered by the user.

        Returns:
            The authenticated SuperAppUser domain object.

        Raises:
            UserNotFoundError: If no user exists with this username.
            InvalidPINError:   If the PIN does not match.
            AccountInactiveError: If the account is deactivated.
        """
        user = self._user_repo.get_by_username(username)
        if user is None:
            raise UserNotFoundError(
                f"No user found with username '{username}'."
            )

        if not user.is_active:
            raise AccountInactiveError(
                f"Account '{username}' is deactivated."
            )

        if user.pin_hash is None or user.pin_hash != self._hash_pin(pin):
            raise InvalidPINError("Incorrect PIN.")

        logger.info(
            "PIN verification successful",
            extra={"user_id": user.user_id, "username": user.username},
        )

        return user

    def change_pin(self, user_id: str, current_pin: str, new_pin: str) -> None:
        """
        Change a user's PIN.

        Args:
            user_id:     The user's unique ID.
            current_pin: The current 6-digit PIN.
            new_pin:     The new 6-digit PIN.

        Raises:
            UserNotFoundError: If the user_id doesn't exist.
            InvalidPINError:   If the current PIN is wrong or new PIN format is invalid.
        """
        user = self._user_repo.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(f"User '{user_id}' not found.")

        if user.pin_hash is None or user.pin_hash != self._hash_pin(current_pin):
            raise InvalidPINError("Current PIN is incorrect.")

        if not new_pin.isdigit() or len(new_pin) != 6:
            raise InvalidPINError("New PIN must be exactly 6 digits.")

        self._user_repo.update_pin_hash(user_id, self._hash_pin(new_pin))

        logger.info(
            "PIN changed",
            extra={"user_id": user_id},
        )


# Custom exceptions
class RegistrationError(Exception):
    """Base exception for user registration errors."""

class InvalidUsernameError(RegistrationError):
    """Raised when a username doesn't meet format requirements."""

class UsernameAlreadyTakenError(RegistrationError):
    """Raised when the requested username is already registered."""

class FINAlreadyRegisteredError(RegistrationError):
    """Raised when the FIN is already linked to an existing account."""

class UserNotFoundError(RegistrationError):
    """Raised when a username lookup finds no matching user."""

class InvalidPINError(RegistrationError):
    """Raised when a PIN doesn't meet format requirements or doesn't match."""

class AccountInactiveError(RegistrationError):
    """Raised when trying to authenticate with a deactivated account."""
