"""
Domain Model: Consent & Pseudonymous Identity
Layer: 🟢 LAYER 1 — Enterprise Business Rules
Rule: ZERO external framework imports. Pure Python + Pydantic only.

The privacy architecture that makes the developer platform safe to open.

Why pseudonyms
--------------
The Fayda Identification Number is Ethiopia's national identity number. If every
onboarded developer received it, then:

  * any single developer breach becomes a national-ID breach, and
  * any two developers could join their datasets on it, reconstructing a
    cross-application profile of a citizen that neither was granted.

India ran this experiment with Aadhaar and had to retrofit it. The Supreme Court
struck down private-entity access in 2018, forcing tokenised reference IDs.
EUPI starts where that ended: developers receive a **per-app pseudonym**, and
the same person integrating with two apps yields two identifiers with no
derivable relationship. Correlation is prevented by construction, not by policy.

What developers get instead
---------------------------
Verified *claims*, not identifiers: "this person is KYC-verified to STANDARD
level and their phone is verified" is the useful part of identity for a lender
or a merchant. The FIN itself is almost never what they actually need.

Consent
-------
Every scope a developer holds against a user is an explicit, revocable grant
with an expiry. A grant that cannot be revoked in one action is not consent.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum

from pydantic import BaseModel, Field


class ConsentScope(str, Enum):
    """
    The catalogue of things a developer application may be granted.

    Deliberately fine-grained on identity: an app that needs to know a user is
    real should not have to request their name to find out.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    IDENTITY_READ_BASIC = "identity:read:basic"
    """Pseudonymous ID, verification status, KYC level. No personal data."""

    IDENTITY_READ_NAME = "identity:read:name"
    """The user's full legal name."""

    IDENTITY_READ_PHONE = "identity:read:phone"
    """The user's phone number."""

    IDENTITY_READ_FIN = "identity:read:fin"
    """
    The raw Fayda Identification Number.

    RESTRICTED. Never granted by default and never bundled with another scope.
    Reserved for callers under an independent regulatory obligation to collect
    it — a licensed lender running its own KYC, for instance. Every read is
    written to the audit trail.
    """

    # ── Money ─────────────────────────────────────────────────────────────────
    ACCOUNTS_READ = "accounts:read"
    """See account balances across linked bank accounts."""

    TRANSACTIONS_READ_OWN = "transactions:read:own"
    """Transactions this application itself initiated. Never another app's."""

    PAYMENTS_INITIATE = "payments:initiate"
    """Initiate payments on the user's behalf."""

    PAYMENTS_READ_OWN = "payments:read:own"
    """Read the status of payments initiated by this app."""

    # ── Platform ──────────────────────────────────────────────────────────────
    WEBHOOKS_RECEIVE = "webhooks:receive"
    """Receive asynchronous payment status callbacks."""

    @property
    def is_restricted(self) -> bool:
        """
        Whether this scope needs individual approval beyond normal onboarding.

        Restricted scopes are never included in a bulk grant and never appear
        in the self-service catalogue.
        """
        return self is ConsentScope.IDENTITY_READ_FIN

    @property
    def is_app_level(self) -> bool:
        """
        Whether an app-only token (client_credentials) may carry this scope.

        App-level scopes touch the application's own records or its integration
        mechanics. Everything touching a user requires a delegated token (tpp_user_access).
        """
        return self in (ConsentScope.PAYMENTS_READ_OWN, ConsentScope.WEBHOOKS_RECEIVE)

    @property
    def requires_user_consent(self) -> bool:
        """
        Whether a user must personally approve this scope.

        Scopes touching personal data always require it. Platform mechanics
        such as webhook delivery or reading the app's own payments do not.
        """
        return self not in (ConsentScope.WEBHOOKS_RECEIVE, ConsentScope.PAYMENTS_READ_OWN)

    @property
    def description(self) -> str:
        """Plain-language explanation, shown to the user on the consent screen."""
        return {
            ConsentScope.IDENTITY_READ_BASIC: (
                "Confirm that you are a verified EUPI user, without sharing your "
                "name or ID number."
            ),
            ConsentScope.IDENTITY_READ_NAME: "See your full name.",
            ConsentScope.IDENTITY_READ_PHONE: "See your phone number.",
            ConsentScope.IDENTITY_READ_FIN: (
                "See your Fayda national ID number. Only licensed providers with "
                "their own legal obligation to verify identity may request this."
            ),
            ConsentScope.ACCOUNTS_READ: "See your account balances across linked banks.",
            ConsentScope.TRANSACTIONS_READ_OWN: (
                "See the transactions you make through this app."
            ),
            ConsentScope.PAYMENTS_INITIATE: "Start payments from your account.",
            ConsentScope.PAYMENTS_READ_OWN: "Read status of payments initiated by this app.",
            ConsentScope.WEBHOOKS_RECEIVE: "Receive payment status updates.",
        }[self]

    @classmethod
    def self_service(cls) -> list["ConsentScope"]:
        """Scopes a developer may request without a separate licensing review."""
        return [scope for scope in cls if not scope.is_restricted]


class ConsentStatus(str, Enum):
    """Lifecycle state of a single grant."""

    GRANTED = "GRANTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class UserAppIdentity(BaseModel):
    """
    The pseudonym a single user presents to a single application.

    `psu_id` is randomly generated and stored, not derived from the user's
    identity. A derived identifier — HMAC(secret, user + app), say — collapses
    the moment the secret leaks: an attacker could recompute every mapping.
    A random value has no such relationship to recover, and it can be rotated.

    "PSU" is Payment Services User, the PSD2 term, kept because it is the
    vocabulary developers integrating with open banking already know.
    """

    psu_id: str = Field(
        ...,
        description="Opaque per-application identifier. The only user ID a developer ever sees.",
        examples=["psu_7f3a9c2e14b84d6fa1e5c8027b93de41"],
    )
    username: str = Field(
        ...,
        description="Internal Super App handle. NEVER exposed to developers.",
        examples=["abebe_girma@eupi"],
    )
    app_id: str = Field(
        ...,
        description="Developer application this pseudonym is scoped to.",
        examples=["app_9f2b1c"],
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
        description="UTC timestamp of first interaction between this user and app.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "psu_id": "psu_7f3a9c2e14b84d6fa1e5c8027b93de41",
                "username": "abebe_girma@eupi",
                "app_id": "app_9f2b1c",
                "created_at": "2026-08-15T10:30:00Z",
            }
        }
    }


class Consent(BaseModel):
    """
    One user's grant of one scope to one application.

    Modelled per scope rather than as a bundle so a user can withdraw a single
    permission without severing the whole integration — revoking "see my name"
    should not also stop payments working.
    """

    consent_id: str = Field(..., description="Unique identifier for this grant.")
    username: str = Field(
        ...,
        description="Internal Super App handle. NEVER exposed to developers.",
    )
    app_id: str = Field(..., description="Developer application holding the grant.")
    scope: ConsentScope = Field(..., description="What was granted.")
    status: ConsentStatus = Field(
        default=ConsentStatus.GRANTED,
        description="Current lifecycle state.",
    )
    granted_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
        description="UTC timestamp the user approved this scope.",
    )
    expires_at: datetime | None = Field(
        default=None,
        description=(
            "UTC expiry. None means open-ended, which should be rare — a grant "
            "with no end is one the user will never think to review."
        ),
    )
    revoked_at: datetime | None = Field(
        default=None,
        description="UTC timestamp of revocation, if revoked.",
    )

    @property
    def is_active(self) -> bool:
        """
        Whether this grant currently authorises anything.

        Expiry is evaluated here rather than by a sweep job, so a lapsed grant
        stops authorising the instant it lapses instead of whenever a cleanup
        task next happens to run.
        """
        if self.status is not ConsentStatus.GRANTED:
            return False
        if self.expires_at is not None and self.expires_at <= datetime.now(tz=timezone.utc):
            return False
        return True

    @property
    def effective_status(self) -> ConsentStatus:
        """Status accounting for lapsed expiry, for display purposes."""
        if self.status is ConsentStatus.GRANTED and not self.is_active:
            return ConsentStatus.EXPIRED
        return self.status

    model_config = {
        "json_schema_extra": {
            "example": {
                "consent_id": "cns_3a7f9e21",
                "username": "abebe_girma@eupi",
                "app_id": "app_9f2b1c",
                "scope": "identity:read:basic",
                "status": "GRANTED",
                "granted_at": "2026-08-15T10:30:00Z",
                "expires_at": "2027-08-15T10:30:00Z",
                "revoked_at": None,
            }
        }
    }


class VerifiedClaims(BaseModel):
    """
    What a developer actually receives about a user.

    Note what is absent: there is no `fin` field, and no `username`. That is the
    entire point — a developer holding every field here still cannot identify
    the person outside their own application, nor match them against another
    developer's records.

    Fields are None when the corresponding scope was not granted, so the same
    response shape serves every permission level.
    """

    psu_id: str = Field(
        ...,
        description="Per-application pseudonym. Stable for this app, meaningless to any other.",
    )
    identity_verified: bool = Field(
        ...,
        description="Whether this person completed Fayda eKYC.",
    )
    kyc_level: str = Field(
        ...,
        description="Assurance level reached, e.g. STANDARD.",
    )
    phone_verified: bool = Field(
        ...,
        description="Whether the phone number was verified by OTP.",
    )
    full_name: str | None = Field(
        default=None,
        description="Present only with identity:read:name.",
    )
    phone_number: str | None = Field(
        default=None,
        description="Present only with identity:read:phone.",
    )
    fin: str | None = Field(
        default=None,
        description=(
            "Present only with the restricted identity:read:fin scope. Every "
            "response carrying this field is written to the audit trail."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "psu_id": "psu_7f3a9c2e14b84d6fa1e5c8027b93de41",
                "identity_verified": True,
                "kyc_level": "STANDARD",
                "phone_verified": True,
                "full_name": "Abebe Girma Tadesse",
                "phone_number": None,
                "fin": None,
            }
        }
    }


def default_consent_expiry(days: int = 365) -> datetime:
    """
    Default expiry for a new grant.

    Bounded by default so a forgotten integration stops reading a user's data
    eventually, even if nobody revisits the consent screen.

    Args:
        days: Lifetime in days.

    Returns:
        UTC expiry timestamp.
    """
    return datetime.now(tz=timezone.utc) + timedelta(days=days)
