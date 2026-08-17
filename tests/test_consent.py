"""
Consent and pseudonymous identity tests.

These cover the privacy guarantees the developer platform will rest on. A
failure here means either that two developers can correlate the same citizen
across their applications, or that a national ID can reach a party that was
never granted it. Treat any failure as a release blocker.

Run:  py -m pytest tests/ -v
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

os.environ.setdefault("DEBUG", "true")

from backend.application.use_cases.consent_service import (  # noqa: E402
    ConsentNotFoundError,
    ConsentService,
    RestrictedScopeError,
    UnknownUserError,
)
from backend.domain.models.consent import (  # noqa: E402
    Consent,
    ConsentScope,
    ConsentStatus,
    VerifiedClaims,
)
from backend.domain.models.user import SuperAppUser  # noqa: E402
from backend.infrastructure.auth.identity_vault import FernetIdentityVault  # noqa: E402
from backend.infrastructure.database.consent_repository import (  # noqa: E402
    ConsentRepository,
    FinVaultRepository,
    UserAppIdentityRepository,
)
from backend.infrastructure.database.session import Database  # noqa: E402
from backend.infrastructure.database.user_repository import (  # noqa: E402
    UserRepository,
)

APP_A = "app_alpha"
APP_B = "app_beta"
FIN = "12345678901234"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    """A fresh SQLite database per test, wired as production wires it."""
    database = Database(url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    database.create_all()
    return database


@pytest.fixture()
def vault() -> FernetIdentityVault:
    """Deterministic test keys, so ciphertext is reproducible across fixtures."""
    return FernetIdentityVault(
        encryption_key="test-encryption-key-for-unit-tests-only",
        blind_index_pepper="test-blind-index-pepper-for-unit-tests",
    )


@pytest.fixture()
def user_repo(db: Database, vault: FernetIdentityVault) -> UserRepository:
    repo = UserRepository(db, vault)
    repo.create_user(
        SuperAppUser(
            username="abebe@eupi",
            fin=FIN,
            full_name="Abebe Girma Tadesse",
            phone_number="+251911234567",
            pin_hash="x",
        )
    )
    return repo


@pytest.fixture()
def service(
    db: Database, user_repo: UserRepository, vault: FernetIdentityVault
) -> ConsentService:
    return ConsentService(
        identity_repo=UserAppIdentityRepository(db),
        consent_repo=ConsentRepository(db),
        vault_repo=FinVaultRepository(db),
        vault=vault,
        user_repo=user_repo,
    )


# ── The core privacy property ─────────────────────────────────────────────────


class TestPseudonymUnlinkability:
    """
    The guarantee the whole design exists to provide: two developers holding
    their complete user lists cannot tell they share a customer.
    """

    def test_same_user_gets_different_ids_per_app(self, service: ConsentService) -> None:
        a = service.resolve_psu_id("abebe@eupi", APP_A)
        b = service.resolve_psu_id("abebe@eupi", APP_B)

        assert a != b, "Same pseudonym across apps would allow direct correlation"

    def test_pseudonym_is_stable_within_an_app(self, service: ConsentService) -> None:
        first = service.resolve_psu_id("abebe@eupi", APP_A)
        second = service.resolve_psu_id("abebe@eupi", APP_A)

        assert first == second, "An app must see a stable ID for a returning user"

    def test_pseudonym_leaks_nothing_about_the_user(self, service: ConsentService) -> None:
        """
        A pseudonym derived from identity would be reversible if the derivation
        secret leaked. This one is random, so it must contain no trace of the
        username or FIN it stands for.
        """
        psu_id = service.resolve_psu_id("abebe@eupi", APP_A)

        assert FIN not in psu_id
        assert "abebe" not in psu_id.lower()
        assert psu_id.startswith("psu_")
        assert len(psu_id) == 36  # "psu_" + 32 hex chars = 128 bits

    def test_an_app_cannot_resolve_another_apps_pseudonym(
        self, service: ConsentService
    ) -> None:
        """
        Without scoping the reverse lookup by app, one developer could present a
        pseudonym harvested elsewhere and confirm it maps to a real user —
        re-enabling the correlation the split IDs prevent.
        """
        psu_a = service.resolve_psu_id("abebe@eupi", APP_A)

        assert service.resolve_username(psu_a, APP_A) == "abebe@eupi"
        assert service.resolve_username(psu_a, APP_B) is None

    def test_unknown_pseudonym_resolves_to_nothing(self, service: ConsentService) -> None:
        assert service.resolve_username("psu_does_not_exist", APP_A) is None


# ── Consent lifecycle ─────────────────────────────────────────────────────────


class TestConsentLifecycle:
    def test_grant_then_check(self, service: ConsentService) -> None:
        assert not service.has_consent("abebe@eupi", APP_A, ConsentScope.IDENTITY_READ_NAME)

        service.grant("abebe@eupi", APP_A, ConsentScope.IDENTITY_READ_NAME)

        assert service.has_consent("abebe@eupi", APP_A, ConsentScope.IDENTITY_READ_NAME)

    def test_consent_does_not_leak_across_apps(self, service: ConsentService) -> None:
        service.grant("abebe@eupi", APP_A, ConsentScope.IDENTITY_READ_NAME)

        assert not service.has_consent("abebe@eupi", APP_B, ConsentScope.IDENTITY_READ_NAME)

    def test_consent_does_not_leak_across_scopes(self, service: ConsentService) -> None:
        service.grant("abebe@eupi", APP_A, ConsentScope.IDENTITY_READ_NAME)

        assert not service.has_consent("abebe@eupi", APP_A, ConsentScope.IDENTITY_READ_PHONE)

    def test_revoking_takes_effect_immediately(self, service: ConsentService) -> None:
        consent = service.grant("abebe@eupi", APP_A, ConsentScope.IDENTITY_READ_NAME)
        assert service.has_consent("abebe@eupi", APP_A, ConsentScope.IDENTITY_READ_NAME)

        service.revoke(consent.consent_id, "abebe@eupi")

        assert not service.has_consent("abebe@eupi", APP_A, ConsentScope.IDENTITY_READ_NAME)

    def test_one_user_cannot_revoke_anothers_consent(
        self, service: ConsentService, user_repo: UserRepository
    ) -> None:
        user_repo.create_user(
            SuperAppUser(
                username="selam@eupi",
                fin="23456789012345",
                full_name="Selamawit Bekele",
                phone_number="+251922345678",
                pin_hash="x",
            )
        )
        victim = service.grant("abebe@eupi", APP_A, ConsentScope.IDENTITY_READ_NAME)

        with pytest.raises(ConsentNotFoundError):
            service.revoke(victim.consent_id, "selam@eupi")

        # Still intact.
        assert service.has_consent("abebe@eupi", APP_A, ConsentScope.IDENTITY_READ_NAME)

    def test_disconnect_revokes_every_scope_at_once(self, service: ConsentService) -> None:
        """
        Disconnecting must not depend on the user remembering every scope they
        granted — one missed permission is a permission still live.
        """
        for scope in (
            ConsentScope.IDENTITY_READ_BASIC,
            ConsentScope.IDENTITY_READ_NAME,
            ConsentScope.IDENTITY_READ_PHONE,
        ):
            service.grant("abebe@eupi", APP_A, scope)
        service.grant("abebe@eupi", APP_B, ConsentScope.IDENTITY_READ_NAME)

        revoked = service.disconnect_app("abebe@eupi", APP_A)

        assert revoked == 3
        assert not service.has_consent("abebe@eupi", APP_A, ConsentScope.IDENTITY_READ_NAME)
        # The other app is untouched.
        assert service.has_consent("abebe@eupi", APP_B, ConsentScope.IDENTITY_READ_NAME)

    def test_expired_consent_stops_authorising(self, service: ConsentService) -> None:
        """
        Expiry is evaluated on read, so a lapsed grant stops working the moment
        it lapses rather than whenever a cleanup job next runs.
        """
        expired = Consent(
            consent_id="cns_expired",
            username="abebe@eupi",
            app_id=APP_A,
            scope=ConsentScope.IDENTITY_READ_NAME,
            status=ConsentStatus.GRANTED,
            granted_at=datetime.now(tz=timezone.utc) - timedelta(days=400),
            expires_at=datetime.now(tz=timezone.utc) - timedelta(days=1),
        )

        assert not expired.is_active
        assert expired.effective_status is ConsentStatus.EXPIRED

    def test_grant_defaults_to_a_bounded_lifetime(self, service: ConsentService) -> None:
        consent = service.grant("abebe@eupi", APP_A, ConsentScope.IDENTITY_READ_NAME)

        assert consent.expires_at is not None, (
            "An open-ended grant is one the user will never revisit"
        )


class TestRestrictedScopes:
    def test_fin_scope_is_restricted(self) -> None:
        assert ConsentScope.IDENTITY_READ_FIN.is_restricted
        assert not ConsentScope.IDENTITY_READ_BASIC.is_restricted

    def test_fin_scope_is_absent_from_self_service(self) -> None:
        assert ConsentScope.IDENTITY_READ_FIN not in ConsentScope.self_service()

    def test_self_service_grant_of_fin_is_refused(self, service: ConsentService) -> None:
        with pytest.raises(RestrictedScopeError):
            service.grant("abebe@eupi", APP_A, ConsentScope.IDENTITY_READ_FIN)

    def test_fin_scope_requires_explicit_override(self, service: ConsentService) -> None:
        consent = service.grant(
            "abebe@eupi", APP_A, ConsentScope.IDENTITY_READ_FIN, allow_restricted=True
        )
        assert consent.scope is ConsentScope.IDENTITY_READ_FIN


# ── Claim assembly ────────────────────────────────────────────────────────────


class TestClaims:
    def test_no_consent_yields_only_non_personal_claims(
        self, service: ConsentService
    ) -> None:
        claims = service.build_claims("abebe@eupi", APP_A)

        assert claims.psu_id.startswith("psu_")
        assert claims.identity_verified is True
        assert claims.kyc_level == "STANDARD"
        # Nothing personal without a grant.
        assert claims.full_name is None
        assert claims.phone_number is None
        assert claims.fin is None

    def test_name_appears_only_with_its_scope(self, service: ConsentService) -> None:
        service.grant("abebe@eupi", APP_A, ConsentScope.IDENTITY_READ_NAME)
        claims = service.build_claims("abebe@eupi", APP_A)

        assert claims.full_name == "Abebe Girma Tadesse"
        assert claims.phone_number is None

    def test_revocation_is_reflected_on_the_next_call(
        self, service: ConsentService
    ) -> None:
        consent = service.grant("abebe@eupi", APP_A, ConsentScope.IDENTITY_READ_NAME)
        assert service.build_claims("abebe@eupi", APP_A).full_name is not None

        service.revoke(consent.consent_id, "abebe@eupi")

        assert service.build_claims("abebe@eupi", APP_A).full_name is None

    def test_claims_never_carry_the_username(self, service: ConsentService) -> None:
        """
        The internal handle is a stable cross-app identifier. Exposing it would
        undo the pseudonymity entirely, so it must not be a field at all.
        """
        service.grant("abebe@eupi", APP_A, ConsentScope.IDENTITY_READ_NAME)
        claims = service.build_claims("abebe@eupi", APP_A)

        assert "username" not in claims.model_dump()
        assert "abebe@eupi" not in claims.model_dump_json()

    def test_fin_reaches_an_app_only_under_the_restricted_scope(
        self, service: ConsentService
    ) -> None:
        service.vault_fin("abebe@eupi", FIN)

        # Every non-restricted scope granted — still no FIN.
        for scope in ConsentScope.self_service():
            if scope.requires_user_consent:
                service.grant("abebe@eupi", APP_A, scope)
        assert service.build_claims("abebe@eupi", APP_A).fin is None

        service.grant(
            "abebe@eupi", APP_A, ConsentScope.IDENTITY_READ_FIN, allow_restricted=True
        )
        assert service.build_claims("abebe@eupi", APP_A).fin == FIN

    def test_unknown_user_raises(self, service: ConsentService) -> None:
        with pytest.raises(UnknownUserError):
            service.build_claims("nobody@eupi", APP_A)


# ── FIN vault ─────────────────────────────────────────────────────────────────


class TestIdentityVault:
    def test_roundtrip(self, vault: FernetIdentityVault) -> None:
        assert vault.decrypt(vault.encrypt(FIN)) == FIN

    def test_ciphertext_is_randomised(self, vault: FernetIdentityVault) -> None:
        """
        Deterministic ciphertext would let anyone with the database tell which
        users share a FIN, and would make the encrypted column itself a
        correlation key.
        """
        assert vault.encrypt(FIN) != vault.encrypt(FIN)

    def test_ciphertext_does_not_contain_the_plaintext(
        self, vault: FernetIdentityVault
    ) -> None:
        assert FIN not in vault.encrypt(FIN)

    def test_blind_index_is_deterministic(self, vault: FernetIdentityVault) -> None:
        """The index must be stable, or equality lookups cannot work."""
        assert vault.blind_index(FIN) == vault.blind_index(FIN)

    def test_blind_index_ignores_surrounding_whitespace(
        self, vault: FernetIdentityVault
    ) -> None:
        """Otherwise a stray space creates a duplicate identity."""
        assert vault.blind_index(f"  {FIN} ") == vault.blind_index(FIN)

    def test_blind_index_is_keyed_not_a_bare_digest(
        self, vault: FernetIdentityVault
    ) -> None:
        """
        A plain SHA-256 of a 14-digit FIN is brute-forceable offline — only 10^14
        candidates. A different pepper must therefore produce a different index.
        """
        import hashlib

        other = FernetIdentityVault(
            encryption_key="test-encryption-key-for-unit-tests-only",
            blind_index_pepper="a-completely-different-pepper-value",
        )
        assert vault.blind_index(FIN) != other.blind_index(FIN)
        assert vault.blind_index(FIN) != hashlib.sha256(FIN.encode()).hexdigest()

    def test_wrong_key_fails_loudly(self, vault: FernetIdentityVault) -> None:
        """Returning a wrong national ID would be worse than failing."""
        ciphertext = vault.encrypt(FIN)
        other = FernetIdentityVault(
            encryption_key="an-entirely-different-encryption-key-value",
            blind_index_pepper="test-blind-index-pepper-for-unit-tests",
        )
        with pytest.raises(ValueError):
            other.decrypt(ciphertext)

    def test_lookup_by_fin_without_decrypting(self, service: ConsentService) -> None:
        service.vault_fin("abebe@eupi", FIN)

        assert service.find_user_by_fin(FIN) == "abebe@eupi"
        assert service.find_user_by_fin("99999999999999") is None


# ── Schema-level guarantee ────────────────────────────────────────────────────


class TestClaimsSchema:
    def test_verified_claims_declares_no_username_field(self) -> None:
        """
        Asserted against the schema rather than an instance: a future field
        addition that reintroduces a cross-app identifier fails here even if no
        test happens to populate it.
        """
        fields = set(VerifiedClaims.model_fields)

        assert "username" not in fields
        assert "user_id" not in fields
        assert fields == {
            "psu_id",
            "identity_verified",
            "kyc_level",
            "phone_verified",
            "full_name",
            "phone_number",
            "fin",
        }
