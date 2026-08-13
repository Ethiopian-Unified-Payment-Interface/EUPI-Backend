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

    def __init__(
        self,
        user_repo: UserRepositoryPort,
        identity_port: IdentityPort | None = None,
    ) -> None:
        self._user_repo = user_repo
        self._identity_port = identity_port

    @staticmethod
    def _hash_pin(pin: str) -> str:
        """Hash a 6-digit PIN with SHA-256. Never store plaintext PINs."""
        return hashlib.sha256(pin.encode()).hexdigest()

    def request_registration_otp(self, fin: str, phone_number: str) -> str:
        """
        Request a Fayda eKYC OTP sent to the phone number registered to the FIN.

        Args:
            fin:          14-digit Fayda Identification Number.
            phone_number: E.164 phone number to verify against Fayda registry.

        Returns:
            Fayda OTP session_id.

        Raises:
            FaydaIdentityNotFoundError: If the FIN is not in Fayda.
            FaydaPhoneMismatchError:    If the entered phone number does not match Fayda.
        """
        from backend.domain.models.identity import FaydaVerifyRequest
        from backend.infrastructure.mock_data.fayda_registry import get_identity

        identity = get_identity(fin)
        if identity is None:
            raise FaydaIdentityNotFoundError(
                f"FIN '{fin}' is not registered in the Fayda National Identity System."
            )

        # Check FIN uniqueness (one account per national ID)
        existing = self._user_repo.get_by_fin(fin)
        if existing is not None:
            raise FINAlreadyRegisteredError(
                "A super app account already exists for this FIN."
            )

        # Verify entered phone number matches the phone number registered to that FIN in Fayda
        fayda_phone_norm = identity["phone_number"].strip().replace(" ", "")
        input_phone_norm = phone_number.strip().replace(" ", "")
        if fayda_phone_norm != input_phone_norm:
            raise FaydaPhoneMismatchError(
                f"Phone number '{phone_number}' does not match the phone number registered "
                f"to FIN '{fin}' in the Fayda National Identity System."
            )

        if self._identity_port is None:
            raise RuntimeError("Identity port not initialized.")

        req = FaydaVerifyRequest(
            fin=fin,
            phone_number=identity["phone_number"],
            consent_scope="superapp:register",
        )
        return self._identity_port.initiate_kyc_verification(req)

    def verify_registration_otp(self, session_id: str, otp_code: str) -> dict[str, str]:
        """
        Step 2 of Registration: Verify the 6-digit OTP code received on customer's phone.

        Args:
            session_id: Fayda OTP session ID from Step 1.
            otp_code:   6-digit OTP code.

        Returns:
            Dict containing registration_token, fin, full_name, phone_number.
        """
        if self._identity_port is None:
            raise RuntimeError("Identity port not initialized.")

        # Inspect session entry to get FIN
        sessions = getattr(self._identity_port, "_sessions", {})
        entry = sessions.get(session_id)
        if entry is None:
            raise InvalidOTPError("Registration OTP session not found, expired, or already consumed.")

        stored_request, _, _ = entry
        fin = stored_request.fin

        kyc_result = self._identity_port.confirm_kyc_otp(
            session_id=session_id,
            otp_code=otp_code,
            fin=fin,
        )

        from backend.infrastructure.mock_data.fayda_registry import get_identity
        identity = get_identity(fin)
        if identity is None:
            raise FaydaIdentityNotFoundError(f"FIN '{fin}' not registered in Fayda.")

        from backend.infrastructure.auth import jwt_handler
        token = jwt_handler.create_registration_token(
            fin=fin,
            full_name=kyc_result.full_name,
            phone_number=identity["phone_number"],
        )

        return {
            "registration_token": token,
            "fin": fin,
            "full_name": kyc_result.full_name,
            "phone_number": identity["phone_number"],
        }

    def complete_registration(
        self,
        registration_token: str,
        username: str,
        pin: str,
    ) -> SuperAppUser:
        """
        Step 3 of Registration: Create user account using verified registration token, username, and 6-digit PIN.

        Args:
            registration_token: Signed token from Step 2 OTP verification.
            username:           Base handle (3-30 chars, alphanumeric + underscores).
            pin:                6-digit numeric login PIN.

        Returns:
            A fully populated SuperAppUser domain object.
        """
        from backend.infrastructure.auth import jwt_handler
        try:
            payload = jwt_handler.decode_registration_token(registration_token)
        except Exception as exc:
            raise InvalidRegistrationTokenError(f"Invalid or expired registration token: {exc}")

        fin = payload["fin"]
        full_name = payload["full_name"]
        phone_number = payload["phone_number"]

        return self.register_user(
            username=username,
            fin=fin,
            full_name=full_name,
            phone_number=phone_number,
            pin=pin,
        )

    def register_user(
        self,
        username: str,
        fin: str,
        full_name: str | None = None,
        phone_number: str | None = None,
        pin: str = "123456",
        session_id: str | None = None,
        otp_code: str | None = None,
    ) -> SuperAppUser:
        """
        Register a new super app user after verifying their Fayda FIN identity and optional OTP.

        Args:
            username:     Base handle (3-30 chars, alphanumeric + underscores).
            fin:          14-digit Fayda Identification Number.
            full_name:    Legal name (pulled/verified from Fayda registry).
            phone_number: E.164 phone number.
            pin:          6-digit numeric login PIN.
            session_id:   Fayda OTP session ID (optional for OTP verification).
            otp_code:     6-digit OTP code sent to customer's phone (optional).

        Returns:
            A fully populated SuperAppUser domain object.
        """
        from backend.infrastructure.mock_data.fayda_registry import get_identity
        fayda_identity = get_identity(fin)

        if fayda_identity is None:
            raise FaydaIdentityNotFoundError(
                f"FIN '{fin}' is not registered in the Fayda National Identity System. "
                "Account creation denied."
            )

        # 1. If OTP session_id and otp_code are provided, verify with FaydaAdapter
        if session_id and otp_code:
            if self._identity_port is None:
                raise RuntimeError("IdentityPort is not configured.")
            kyc_result = self._identity_port.confirm_kyc_otp(
                session_id=session_id,
                otp_code=otp_code,
                fin=fin,
            )
            verified_full_name = kyc_result.full_name
            verified_phone = fayda_identity["phone_number"]
        else:
            verified_full_name = full_name or fayda_identity["full_name"]
            verified_phone = phone_number or fayda_identity["phone_number"]

        # Validate base username format
        from backend.domain.models.user import get_base_username, normalize_username
        base_handle = get_base_username(username)
        if not _USERNAME_PATTERN.match(base_handle):
            raise InvalidUsernameError(
                f"Username '{username}' is invalid. Must be 3-30 characters, "
                "alphanumeric and underscores only."
            )

        # Check username uniqueness
        full_username = normalize_username(username)
        if self._user_repo.username_exists(full_username):
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
            username=full_username,
            fin=fin,
            full_name=verified_full_name,
            phone_number=verified_phone,
            pin_hash=self._hash_pin(pin),
            created_at=datetime.now(tz=timezone.utc),
            is_active=True,
        )

        self._user_repo.create_user(user)

        logger.info(
            "Super app user registered",
            extra={"username": user.username},
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
        from backend.domain.models.user import normalize_username
        full_username = normalize_username(username)
        user = self._user_repo.get_by_username(full_username)
        if user is None:
            raise UserNotFoundError(
                f"No user found with username '{username}'."
            )

        return PublicUserProfile(
            username=user.username,
            full_name=user.full_name,
        )

    def verify_pin(self, username: str, pin: str) -> tuple[SuperAppUser, str]:
        """
        Verify a user's PIN for app login and issue a session JWT.

        Args:
            username: The unique handle of the user.
            pin:      The 6-digit PIN entered by the user.

        Returns:
            A tuple of (authenticated SuperAppUser, session_token).

        Raises:
            UserNotFoundError: If no user exists with this username.
            InvalidPINError:   If the PIN does not match.
            AccountInactiveError: If the account is deactivated.
        """
        from backend.domain.models.user import normalize_username
        full_username = normalize_username(username)
        user = self._user_repo.get_by_username(full_username)
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

        from backend.infrastructure.auth.jwt_handler import create_superapp_session_jwt
        from backend.main import get_repo
        token, jti, expires_at = create_superapp_session_jwt(user.username, user.fin)
        try:
            get_repo().save_token(
                jti=jti,
                fin=user.fin,
                kyc_level="STANDARD",
                scopes=["superapp:user"],
                issued_at=datetime.now(tz=timezone.utc),
                expires_at=expires_at,
            )
        except Exception:
            pass

        logger.info(
            "PIN verification successful",
            extra={"username": user.username},
        )

        return user, token

    def change_pin(self, username: str, current_pin: str, new_pin: str) -> None:
        """
        Change a user's PIN.

        Args:
            username:    The user's unique username.
            current_pin: The current 6-digit PIN.
            new_pin:     The new 6-digit PIN.

        Raises:
            UserNotFoundError: If the username doesn't exist.
            InvalidPINError:   If the current PIN is wrong or new PIN format is invalid.
        """
        from backend.domain.models.user import normalize_username
        full_username = normalize_username(username)
        user = self._user_repo.get_by_username(full_username)
        if user is None:
            raise UserNotFoundError(f"User '{username}' not found.")

        if user.pin_hash is None or user.pin_hash != self._hash_pin(current_pin):
            raise InvalidPINError("Current PIN is incorrect.")

        if not new_pin.isdigit() or len(new_pin) != 6:
            raise InvalidPINError("New PIN must be exactly 6 digits.")

        self._user_repo.update_pin_hash(full_username, self._hash_pin(new_pin))

        logger.info(
            "PIN changed",
            extra={"username": full_username},
        )


# Custom exceptions
class RegistrationError(Exception):
    """Base exception for user registration errors."""

class FaydaIdentityNotFoundError(RegistrationError):
    """Raised when the FIN is not found in the Fayda National Identity System."""

class FaydaPhoneMismatchError(RegistrationError):
    """Raised when the entered phone number does not match the Fayda registered phone number."""

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

class InvalidOTPError(RegistrationError):
    """Raised when an OTP code is invalid or expired."""

class InvalidRegistrationTokenError(RegistrationError):
    """Raised when a registration verification token is invalid or expired."""

class AccountInactiveError(RegistrationError):
    """Raised when trying to authenticate with a deactivated account."""
