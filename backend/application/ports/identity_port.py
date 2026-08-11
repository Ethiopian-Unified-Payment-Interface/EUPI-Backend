"""
Port: IdentityPort
Layer: 🟡 LAYER 2 — Application / Ports & Use Cases
Rule: Abstract interface only. NO concrete implementation. NO HTTP calls.

Defines the contract for identity verification operations. The Fayda adapter
in the infrastructure layer MUST implement this ABC. The use-case layer depends
only on this abstract class — it has no knowledge of Fayda's real API.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

# Domain imports only — never infrastructure or presentation.
from backend.domain.models.identity import FaydaKYCResult, FaydaVerifyRequest, KYCLevel


class IdentityPort(ABC):
    """
    Abstract Driven Port: Identity Verification Interface.

    Provides eKYC (electronic Know Your Customer) for end-users and supports
    KYB (Know Your Business) checks for developer onboarding.

    Concrete implementation: infrastructure/adapters/identity/fayda.py
    """

    @abstractmethod
    def initiate_kyc_verification(self, request: FaydaVerifyRequest) -> str:
        """
        Trigger the Fayda OTP dispatch and initiate an eKYC session.

        The adapter sends an OTP to the customer's registered phone number
        via the Fayda system. The returned session_id must be presented with
        the OTP in the subsequent :meth:`confirm_kyc_otp` call.

        Args:
            request: A :class:`~domain.models.identity.FaydaVerifyRequest` containing
                     the customer's FIN, phone number, required KYC level, and
                     consent scopes.

        Returns:
            A short-lived session_id string (opaque token) that identifies this
            verification attempt. Typically expires in 5 minutes.

        Raises:
            IdentityProviderError:   If Fayda is unreachable or returns an error.
            InvalidFINError:         If the FIN does not match any Fayda record.
            RateLimitError:          If too many OTP requests were sent recently.
        """
        ...

    @abstractmethod
    def confirm_kyc_otp(
        self,
        session_id: str,
        otp_code: str,
        fin: str,
    ) -> FaydaKYCResult:
        """
        Validate the customer-submitted OTP against the active Fayda session.

        On success, Fayda returns the verified identity data which the adapter
        normalises to :class:`~domain.models.identity.FaydaKYCResult`.

        Args:
            session_id: The session_id returned by :meth:`initiate_kyc_verification`.
            otp_code:   The 6-digit OTP entered by the customer.
            fin:        The customer's FIN (used to cross-verify the session).

        Returns:
            A :class:`~domain.models.identity.FaydaKYCResult` containing the
            verified identity attributes and a consent_token for downstream use.

        Raises:
            InvalidOTPError:         If the OTP is wrong or has expired.
            SessionExpiredError:     If the session_id has timed out.
            KYCLevelNotMetError:     If the verification result does not satisfy
                                     the required_kyc_level from the original request.
            IdentityProviderError:   If Fayda is unreachable.
        """
        ...

    @abstractmethod
    def verify_consent_token(self, consent_token: str) -> bool:
        """
        Validate that a consent_token is authentic, unexpired, and not revoked.

        Called by the gateway at the start of every protected AIS/PIS request
        to ensure the customer's consent is still active.

        Args:
            consent_token: The opaque token issued by :meth:`confirm_kyc_otp`.

        Returns:
            True if the token is valid and the associated consent is still active.
            False if the token has expired, been revoked, or is malformed.

        Raises:
            IdentityProviderError: If the token verification service is unreachable.
        """
        ...

    @abstractmethod
    def get_kyc_level_for_token(self, consent_token: str) -> KYCLevel:
        """
        Retrieve the KYC assurance level associated with a valid consent token.

        Used by the routing and authorisation logic to enforce minimum KYC
        levels for high-value operations (e.g., PIS requires STANDARD or above).

        Args:
            consent_token: A valid consent token.

        Returns:
            The :class:`~domain.models.identity.KYCLevel` achieved during the
            original verification session.

        Raises:
            InvalidTokenError:     If the token is invalid or expired.
            IdentityProviderError: If the provider is unreachable.
        """
        ...
