"""
End-to-end Super App journey: registration → account linking → default bank
selection → handle-based P2P transfer → ledger → transaction history.

Runs the real FastAPI application in-process against a throwaway SQLite
database, so it exercises the actual routers, DI graph, and lifespan rather
than calling services directly. No server or container required.

The load-bearing assertion is in `TestHandleBasedTransfer`: a transfer
addressed only by username must resolve the debtor from the *sender's* default
SENDING account and the creditor from the *recipient's* default RECEIVING
account. Several tests change those defaults and re-send to prove the routing
follows them rather than picking the first linked account or a hardcoded bank.

Run:  py -m pytest tests/test_e2e_superapp_p2p.py -v
"""

from __future__ import annotations

import os
import uuid
from decimal import Decimal
from typing import Any, Iterator

import pytest

# The database URL and DEBUG come from tests/conftest.py, which is imported
# before any test module. Setting them here instead only worked when this module
# happened to be imported first.

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402

# ── Fixture data ──────────────────────────────────────────────────────────────
#
# FINs and phone numbers must match the mock Fayda registry, and account
# numbers must match the account-holder maps in the CBS adapters — linking
# refuses an account whose holder name differs from the Fayda identity, which
# is itself behaviour worth relying on.

ABEBE = {
    "fin": "12345678901234",
    "phone": "+251911234567",
    "username": "abebe_e2e",
    "pin": "111222",
    "full_name": "Abebe Girma Tadesse",
    # Both belong to Abebe in the adapter maps.
    "coop_account": "1000234567890",
    "cbe_account": "1000111222333",
}

SELAM = {
    "fin": "23456789012345",
    "phone": "+251922345678",
    "username": "selam_e2e",
    "pin": "333444",
    "full_name": "Selamawit Bekele Hailu",
    "coop_account": "1000987654321",
    "cbe_account": "1000444555666",
}

DANIEL = {
    "fin": "21872187218777",
    "phone": "+251904267039",
    "username": "daniel_e2e",
    "pin": "555666",
    "full_name": "Daniel Kebede Woldetsadik",
    "coop_account": "1000101010101",
}


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    """The real app, with its lifespan run so the DI graph is wired."""
    with TestClient(app) as test_client:
        yield test_client


# ── Helpers ───────────────────────────────────────────────────────────────────


def register(client: TestClient, person: dict[str, str]) -> str:
    """
    Complete the three-step registration and return a session token.

    Idempotent across the module: a person already registered just logs in.
    """
    otp = client.post(
        "/v1/superapp/users/register/request-otp",
        json={"fin": person["fin"], "phone_number": person["phone"]},
    )
    if otp.status_code == 200:
        session_id = otp.json()["session_id"]
        verified = client.post(
            "/v1/superapp/users/register/verify-otp",
            json={"session_id": session_id, "otp_code": "123456"},
        )
        assert verified.status_code == 200, verified.text

        created = client.post(
            "/v1/superapp/users/register/complete",
            json={
                "registration_token": verified.json()["registration_token"],
                "username": person["username"],
                "pin": person["pin"],
            },
        )
        assert created.status_code in (200, 201), created.text

    return login(client, person)


def login(client: TestClient, person: dict[str, str]) -> str:
    response = client.post(
        "/v1/superapp/users/login",
        json={"username": person["username"], "pin": person["pin"]},
    )
    assert response.status_code == 200, response.text
    return response.json()["session_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def link(
    client: TestClient, person: dict[str, str], token: str, bank: str, account: str
) -> str:
    """
    Link a bank account and return its link_id.

    Idempotent, because linking the same account twice is now refused and
    several tests share the same setup. A duplicate attempt resolves the
    existing link rather than failing — which also exercises that refusal.
    """
    response = client.post(
        "/v1/superapp/accounts/link",
        headers=auth(token),
        json={
            "username": person["username"],
            "bank_id": bank,
            "account_number": account,
        },
    )
    if response.status_code in (200, 201):
        return response.json()["link_id"]

    assert "already linked" in response.text.lower(), response.text
    existing = next(
        a for a in accounts_of(client, token)
        if a["bank_id"] == bank and a["account_number"] == account
    )
    return existing["link_id"]


def set_default(
    client: TestClient, person: dict[str, str], token: str, link_id: str, direction: str
) -> None:
    response = client.put(
        f"/v1/superapp/accounts/{link_id}/default",
        headers=auth(token),
        json={"username": person["username"], "direction": direction},
    )
    assert response.status_code == 200, response.text


def accounts_of(client: TestClient, token: str) -> list[dict[str, Any]]:
    response = client.get("/v1/superapp/accounts/sync", headers=auth(token))
    assert response.status_code == 200, response.text
    return response.json()


def available_balance(
    accounts: list[dict[str, Any]], bank_id: str, account_number: str
) -> Decimal:
    """Live CBS balance of one linked account, as the Super App would show it."""
    row = next(
        a
        for a in accounts
        if a["bank_id"] == bank_id and a["account_number"] == account_number
    )
    return Decimal(str(row["available_balance"]))


def admin_token(client: TestClient) -> str:
    # Read the bootstrap credentials rather than repeating them: conftest sets
    # them with setdefault, so a developer with either already exported in their
    # shell would otherwise fail this login against a differently-seeded admin.
    response = client.post(
        "/v1/admin/auth/login",
        json={
            "email": os.environ["ADMIN_BOOTSTRAP_EMAIL"],
            "password": os.environ["ADMIN_BOOTSTRAP_PASSWORD"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def gateway_consent_token(client: TestClient, person: dict[str, str]) -> str:
    """
    Obtain a Fayda gateway consent token.

    PIS VERIFY requires a `gateway_access` token, and a Super App session token
    is deliberately not interchangeable with one — the type check that enforces
    that is the fix for the token-confusion issue in Phase 0. So completing a
    payment means the payer consents through Fayda, separately from having
    logged into the Super App.
    """
    dispatched = client.post(
        "/v1/auth/fayda",
        json={
            "fin": person["fin"],
            "phone_number": person["phone"],
            "consent_scope": "accounts:read,payments:write",
        },
    )
    # 202 Accepted: the OTP is dispatched asynchronously.
    assert dispatched.status_code in (200, 202), dispatched.text

    confirmed = client.post(
        "/v1/auth/fayda/confirm",
        json={
            "session_id": dispatched.json()["session_id"],
            "otp_code": "123456",
            "fin": person["fin"],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()["access_token"]


def settle(client: TestClient, payment_id: str) -> None:
    """
    Fire the bank's settlement callback, taking an ORDERED payment to SUCCESS.

    A PIN-authorised transfer already ran initiate → verify → order server-side,
    so this is the only step left. In production the bank calls this itself.
    """
    callback = client.post(
        "/v1/callbacks",
        json={
            "payment_id": payment_id,
            "bank_order_reference": f"E2E-{payment_id[:8]}",
            "confirmed": True,
        },
    )
    assert callback.status_code == 200, callback.text


# ── 1. Registration ───────────────────────────────────────────────────────────


class TestRegistration:
    def test_three_step_registration_issues_a_session(self, client: TestClient) -> None:
        token = register(client, ABEBE)
        assert token

        profile = client.get(f"/v1/superapp/users/profile/{ABEBE['username']}")
        assert profile.status_code == 200, profile.text
        assert profile.json()["full_name"] == ABEBE["full_name"]

    def test_registration_requires_the_fayda_registered_phone(
        self, client: TestClient
    ) -> None:
        """A FIN alone must not be enough — the phone has to match Fayda."""
        response = client.post(
            "/v1/superapp/users/register/request-otp",
            json={"fin": SELAM["fin"], "phone_number": "+251900000000"},
        )
        assert response.status_code >= 400
        assert "does not match" in response.text

    def test_wrong_otp_is_rejected(self, client: TestClient) -> None:
        otp = client.post(
            "/v1/superapp/users/register/request-otp",
            json={"fin": DANIEL["fin"], "phone_number": DANIEL["phone"]},
        )
        assert otp.status_code == 200, otp.text
        bad = client.post(
            "/v1/superapp/users/register/verify-otp",
            json={"session_id": otp.json()["session_id"], "otp_code": "000000"},
        )
        assert bad.status_code >= 400

    def test_one_account_per_national_id(self, client: TestClient) -> None:
        """
        Enforced through the blind index, so no plaintext FIN is compared.

        The refusal happens at request-otp rather than at completion, which is
        the better place: no OTP is dispatched and no registration token is
        minted for an identity that already has an account.
        """
        register(client, ABEBE)  # already exists

        duplicate = client.post(
            "/v1/superapp/users/register/request-otp",
            json={"fin": ABEBE["fin"], "phone_number": ABEBE["phone"]},
        )
        assert duplicate.status_code >= 400, (
            "A second registration for the same FIN must be refused"
        )
        assert "already" in duplicate.text.lower()


# ── 2. Account linking ────────────────────────────────────────────────────────


class TestAccountLinking:
    def test_link_two_accounts_across_two_banks(self, client: TestClient) -> None:
        token = register(client, ABEBE)

        link(client, ABEBE, token, "COOP", ABEBE["coop_account"])
        link(client, ABEBE, token, "CBE", ABEBE["cbe_account"])

        linked = accounts_of(client, token)
        banks = {a["bank_id"] for a in linked}
        assert {"COOP", "CBE"} <= banks

    def test_linking_someone_elses_account_is_refused(
        self, client: TestClient
    ) -> None:
        """
        The account holder name must match the Fayda identity. Without this a
        user could attach a stranger's account and drain it.
        """
        token = register(client, ABEBE)
        response = client.post(
            "/v1/superapp/accounts/link",
            headers=auth(token),
            json={
                "username": ABEBE["username"],
                "bank_id": "COOP",
                # Belongs to Selamawit in the adapter map.
                "account_number": SELAM["coop_account"],
            },
        )
        assert response.status_code >= 400
        assert "does not match" in response.text

    def test_linking_the_same_account_twice_is_refused(
        self, client: TestClient
    ) -> None:
        """
        A duplicate link is not cosmetic. The aggregated balance sums every
        linked account, so a second row for one account shows the user money
        they do not have — and default resolution takes the first match, so two
        rows can carry conflicting default flags and make the account used for a
        transfer ambiguous.
        """
        token = register(client, ABEBE)
        link(client, ABEBE, token, "COOP", ABEBE["coop_account"])

        duplicate = client.post(
            "/v1/superapp/accounts/link",
            headers=auth(token),
            json={
                "username": ABEBE["username"],
                "bank_id": "COOP",
                "account_number": ABEBE["coop_account"],
            },
        )
        assert duplicate.status_code >= 400, duplicate.text
        assert "already linked" in duplicate.text.lower()

        matching = [
            a for a in accounts_of(client, token)
            if a["bank_id"] == "COOP" and a["account_number"] == ABEBE["coop_account"]
        ]
        assert len(matching) == 1, f"expected one link, found {len(matching)}"

    def test_aggregated_balance_counts_each_account_once(
        self, client: TestClient
    ) -> None:
        """The failure mode a duplicate link caused: an inflated total."""
        token = register(client, ABEBE)
        link(client, ABEBE, token, "COOP", ABEBE["coop_account"])
        link(client, ABEBE, token, "CBE", ABEBE["cbe_account"])

        linked = accounts_of(client, token)
        keys = [(a["bank_id"], a["account_number"]) for a in linked]
        assert len(keys) == len(set(keys)), f"duplicate accounts in list: {keys}"

    def test_linked_accounts_carry_live_balances(self, client: TestClient) -> None:
        token = register(client, ABEBE)
        for account in accounts_of(client, token):
            assert float(account["available_balance"]) > 0


# ── 3. Default sending / receiving banks ──────────────────────────────────────


class TestDefaultBankSelection:
    def test_setting_a_default_is_exclusive_per_direction(
        self, client: TestClient
    ) -> None:
        """
        Exactly one account may be the default for a direction. Two would make
        transfer routing ambiguous, and the resolver takes the first match.
        """
        token = register(client, ABEBE)
        linked = accounts_of(client, token)
        coop = next(a for a in linked if a["bank_id"] == "COOP")
        cbe = next(a for a in linked if a["bank_id"] == "CBE")

        set_default(client, ABEBE, token, coop["link_id"], "SENDING")
        after_coop = accounts_of(client, token)
        assert [a["bank_id"] for a in after_coop if a["is_default_sending"]] == ["COOP"]

        # Moving the default must clear the previous holder, not add a second.
        set_default(client, ABEBE, token, cbe["link_id"], "SENDING")
        after_cbe = accounts_of(client, token)
        senders = [a["bank_id"] for a in after_cbe if a["is_default_sending"]]
        assert senders == ["CBE"], f"expected exactly one default sender, got {senders}"

    def test_sending_and_receiving_defaults_are_independent(
        self, client: TestClient
    ) -> None:
        token = register(client, ABEBE)
        linked = accounts_of(client, token)
        coop = next(a for a in linked if a["bank_id"] == "COOP")
        cbe = next(a for a in linked if a["bank_id"] == "CBE")

        set_default(client, ABEBE, token, cbe["link_id"], "SENDING")
        set_default(client, ABEBE, token, coop["link_id"], "RECEIVING")

        final = accounts_of(client, token)
        assert [a["bank_id"] for a in final if a["is_default_sending"]] == ["CBE"]
        assert [a["bank_id"] for a in final if a["is_default_receiving"]] == ["COOP"]


# ── 4. Handle-based P2P transfer — the core flow ──────────────────────────────


class TestHandleBasedTransfer:
    @pytest.fixture()
    def parties(self, client: TestClient) -> dict[str, Any]:
        """
        Both users registered and linked, with deliberately *different*
        defaults on each side so a transfer cannot accidentally look correct:

            Abebe  sends   from CBE   (receives on COOP)
            Selam  receives on COOP   (sends    from CBE)
        """
        sender_token = register(client, ABEBE)
        link(client, ABEBE, sender_token, "COOP", ABEBE["coop_account"])
        link(client, ABEBE, sender_token, "CBE", ABEBE["cbe_account"])

        recipient_token = register(client, SELAM)
        link(client, SELAM, recipient_token, "COOP", SELAM["coop_account"])
        link(client, SELAM, recipient_token, "CBE", SELAM["cbe_account"])

        sender_accounts = accounts_of(client, sender_token)
        recipient_accounts = accounts_of(client, recipient_token)

        set_default(
            client, ABEBE, sender_token,
            next(a for a in sender_accounts if a["bank_id"] == "CBE")["link_id"],
            "SENDING",
        )
        set_default(
            client, SELAM, recipient_token,
            next(a for a in recipient_accounts if a["bank_id"] == "COOP")["link_id"],
            "RECEIVING",
        )

        return {
            "sender_token": sender_token,
            "recipient_token": recipient_token,
        }

    def test_transfer_by_username_resolves_both_defaults(
        self, client: TestClient, parties: dict[str, Any]
    ) -> None:
        """
        The whole point of handle-based transfer: the caller supplies two
        usernames and an amount, and the platform derives four banking details.
        """
        response = client.post(
            "/v1/superapp/transfers",
            headers=auth(parties["sender_token"]),
            json={
                "sender_username": ABEBE["username"],
                "recipient_username": SELAM["username"],
                "amount": 250.75,
                "pin": ABEBE["pin"],
                "currency": "ETB",
                "remittance_info": "E2E handle transfer",
            },
        )
        assert response.status_code in (200, 201), response.text
        payment_id = response.json()["payment_id"]

        # Read the payment back and assert the resolution.
        payment = client.get(
            f"/v1/payments/{payment_id}", headers=auth(parties["sender_token"])
        )
        assert payment.status_code == 200, payment.text
        body = payment.json()

        assert body["debtor_bank_id"] == "CBE", (
            "Debtor must come from the sender's default SENDING account, "
            f"got {body['debtor_bank_id']}"
        )
        assert body["creditor_bank_id"] == "COOP", (
            "Creditor must come from the recipient's default RECEIVING account, "
            f"got {body['creditor_bank_id']}"
        )
        assert body["creditor_name"] == SELAM["full_name"]
        assert str(body["amount"]) == "250.75"

        # The payment response omits account numbers by design, so the exact
        # accounts are asserted once the payment settles and the ledger records
        # which accounts actually moved. See TestSettlementAndLedger.

    def test_changing_the_default_reroutes_the_next_transfer(
        self, client: TestClient, parties: dict[str, Any]
    ) -> None:
        """
        Strongest evidence the resolution is real: move the sender's default
        and the next transfer must debit the new bank.
        """
        sender_token = parties["sender_token"]
        sender_accounts = accounts_of(client, sender_token)
        coop_link = next(a for a in sender_accounts if a["bank_id"] == "COOP")["link_id"]

        set_default(client, ABEBE, sender_token, coop_link, "SENDING")

        response = client.post(
            "/v1/superapp/transfers",
            headers=auth(sender_token),
            json={
                "sender_username": ABEBE["username"],
                "recipient_username": SELAM["username"],
                "amount": 10.00,
                "pin": ABEBE["pin"],
            },
        )
        assert response.status_code in (200, 201), response.text

        payment = client.get(
            f"/v1/payments/{response.json()['payment_id']}", headers=auth(sender_token)
        ).json()
        assert payment["debtor_bank_id"] == "COOP", (
            "Moving the sender's default SENDING account must reroute the debit"
        )

    def test_debit_hits_the_senders_bank_not_the_routed_rail(
        self, client: TestClient, parties: dict[str, Any]
    ) -> None:
        """
        The catalogue reuses account numbers across banks. Ordering through
        the Smart Router's selected rail — which is often CBE — therefore
        used to debit CBE's copy of the number and leave the sender's real
        COOP account untouched. The Super App then showed SUCCESS, a credit
        on the recipient, and no debit on the payer.
        """
        import backend.main as main_module
        from backend.domain.models.account import BankID

        sender_token = parties["sender_token"]
        set_default(
            client, ABEBE, sender_token,
            next(a for a in accounts_of(client, sender_token) if a["bank_id"] == "COOP")["link_id"],
            "SENDING",
        )

        engine = main_module.get_cbs_engine()
        coop_before = engine.get_account(BankID.COOP, ABEBE["coop_account"]).available_balance
        rail_shadow_before = engine.get_account(
            BankID.CBE, ABEBE["coop_account"]
        ).available_balance

        response = client.post(
            "/v1/superapp/transfers",
            headers=auth(sender_token),
            json={
                "sender_username": ABEBE["username"],
                "recipient_username": SELAM["username"],
                "amount": 40.00,
                "pin": ABEBE["pin"],
            },
        )
        assert response.status_code in (200, 201), response.text
        body = response.json()
        assert body["status"] == "SUCCESS", body
        assert body["debtor_bank_id"] == "COOP"

        total_debited = Decimal(str(body["total_debited"]))
        coop_after = engine.get_account(BankID.COOP, ABEBE["coop_account"]).available_balance
        rail_shadow_after = engine.get_account(
            BankID.CBE, ABEBE["coop_account"]
        ).available_balance

        assert coop_before - coop_after == total_debited, (
            f"Sender's COOP account should fall by {total_debited}, "
            f"fell by {coop_before - coop_after}"
        )
        assert rail_shadow_after == rail_shadow_before, (
            "The routed rail must not debit another bank's copy of the "
            "same account number"
        )

    def test_intra_bank_when_both_defaults_are_the_same_bank(
        self, client: TestClient, parties: dict[str, Any]
    ) -> None:
        """
        Both sides defaulting to COOP must produce an INTRA_BANK payment —
        the cheaper, settlement-free case the fee engine prices separately.
        """
        sender_token = parties["sender_token"]
        recipient_token = parties["recipient_token"]

        set_default(
            client, ABEBE, sender_token,
            next(a for a in accounts_of(client, sender_token) if a["bank_id"] == "COOP")["link_id"],
            "SENDING",
        )
        set_default(
            client, SELAM, recipient_token,
            next(a for a in accounts_of(client, recipient_token) if a["bank_id"] == "COOP")["link_id"],
            "RECEIVING",
        )

        response = client.post(
            "/v1/superapp/transfers",
            headers=auth(sender_token),
            json={
                "sender_username": ABEBE["username"],
                "recipient_username": SELAM["username"],
                "amount": 100.00,
                "pin": ABEBE["pin"],
            },
        )
        assert response.status_code in (200, 201), response.text
        payment = client.get(
            f"/v1/payments/{response.json()['payment_id']}", headers=auth(sender_token)
        ).json()

        assert payment["debtor_bank_id"] == payment["creditor_bank_id"] == "COOP"

    def test_a_session_token_alone_cannot_move_money(
        self, client: TestClient, parties: dict[str, Any]
    ) -> None:
        """
        The PIN is the consent, not the session.

        A session token is a bearer credential valid for an hour. If holding
        one were sufficient to transfer money, a leaked token would be enough to
        drain an account — a weaker bar than the Fayda OTP this path replaces.
        """
        response = client.post(
            "/v1/superapp/transfers",
            headers=auth(parties["sender_token"]),
            json={
                "sender_username": ABEBE["username"],
                "recipient_username": SELAM["username"],
                "amount": 10.00,
                # No pin.
            },
        )
        assert response.status_code == 422, response.text
        assert "pin" in response.text.lower()

    def test_wrong_pin_is_refused_and_moves_no_money(
        self, client: TestClient, parties: dict[str, Any]
    ) -> None:
        before = client.get(
            "/v1/superapp/transactions", headers=auth(parties["sender_token"])
        ).json()["total"]

        response = client.post(
            "/v1/superapp/transfers",
            headers=auth(parties["sender_token"]),
            json={
                "sender_username": ABEBE["username"],
                "recipient_username": SELAM["username"],
                "amount": 10.00,
                "pin": "000000",
            },
        )
        assert response.status_code == 401, response.text

        after = client.get(
            "/v1/superapp/transactions", headers=auth(parties["sender_token"])
        ).json()["total"]
        assert after == before, "A rejected PIN must not create a payment"

    def test_pin_authorised_transfer_debits_sender_and_credits_recipient(
        self, client: TestClient, parties: dict[str, Any]
    ) -> None:
        """
        The gap this closed: a PIN-authorised P2P used to stop at ORDERED,
        which the Super App renders as pending, and never posted the debit
        or the credit. A completed transfer must move money on both books
        and return SUCCESS in the same request.
        """
        sender_before = available_balance(
            accounts_of(client, parties["sender_token"]),
            "CBE",
            ABEBE["cbe_account"],
        )
        recipient_before = available_balance(
            accounts_of(client, parties["recipient_token"]),
            "COOP",
            SELAM["coop_account"],
        )

        amount = Decimal("25.00")
        response = client.post(
            "/v1/superapp/transfers",
            headers=auth(parties["sender_token"]),
            json={
                "sender_username": ABEBE["username"],
                "recipient_username": SELAM["username"],
                "amount": float(amount),
                "pin": ABEBE["pin"],
            },
        )
        assert response.status_code in (200, 201), response.text
        body = response.json()
        assert body["status"] == "SUCCESS", (
            "A PIN-authorised transfer must complete — debit the sender and "
            f"credit the recipient — not remain {body['status']}"
        )

        total_debited = Decimal(str(body["total_debited"]))
        sender_after = available_balance(
            accounts_of(client, parties["sender_token"]),
            "CBE",
            ABEBE["cbe_account"],
        )
        recipient_after = available_balance(
            accounts_of(client, parties["recipient_token"]),
            "COOP",
            SELAM["coop_account"],
        )

        assert sender_before - sender_after == total_debited, (
            f"Sender CBE balance should fall by {total_debited}, "
            f"fell by {sender_before - sender_after}"
        )
        assert recipient_after - recipient_before == amount, (
            f"Recipient COOP balance should rise by {amount}, "
            f"rose by {recipient_after - recipient_before}"
        )

        sender_history = client.get(
            "/v1/superapp/transactions", headers=auth(parties["sender_token"])
        ).json()["transactions"]
        recipient_history = client.get(
            "/v1/superapp/transactions", headers=auth(parties["recipient_token"])
        ).json()["transactions"]
        matching_out = [
            t for t in sender_history if t["payment_id"] == body["payment_id"]
        ]
        matching_in = [
            t for t in recipient_history if t["payment_id"] == body["payment_id"]
        ]
        assert matching_out and matching_out[0]["status"] == "SUCCESS"
        assert matching_out[0]["is_credit"] is False
        assert matching_in and matching_in[0]["status"] == "SUCCESS"
        assert matching_in[0]["is_credit"] is True

    def test_repeating_a_client_reference_does_not_send_twice(
        self, client: TestClient, parties: dict[str, Any]
    ) -> None:
        """
        A single call now moves money, so a double-tapped button or a retried
        request must not produce two transfers.
        """
        payload = {
            "sender_username": ABEBE["username"],
            "recipient_username": SELAM["username"],
            "amount": 15.00,
            "pin": ABEBE["pin"],
            "client_reference": f"idem-{uuid.uuid4().hex[:8]}",
        }

        first = client.post(
            "/v1/superapp/transfers", headers=auth(parties["sender_token"]), json=payload
        )
        assert first.status_code in (200, 201), first.text

        second = client.post(
            "/v1/superapp/transfers", headers=auth(parties["sender_token"]), json=payload
        )
        assert second.status_code in (200, 201), second.text

        # The same payment comes back rather than a second one being sent.
        assert second.json()["payment_id"] == first.json()["payment_id"], (
            "A repeated client_reference must return the original payment, "
            "not create another transfer"
        )

        # And the history gained exactly one entry, not two.
        history = client.get(
            "/v1/superapp/transactions", headers=auth(parties["sender_token"])
        ).json()["transactions"]
        matching = [
            t for t in history if t["end_to_end_id"] == f"P2P-REF-{payload['client_reference']}"
        ]
        assert len(matching) == 1, f"expected one transfer, found {len(matching)}"

    def test_consent_method_is_recorded_on_the_payment(
        self, client: TestClient, parties: dict[str, Any]
    ) -> None:
        """
        An auditor must be able to tell a PIN-authorised payment from an
        OTP-authorised one — they are not equivalent evidence of consent.
        """
        import backend.main as main_module
        from backend.infrastructure.auth import jwt_handler

        created = client.post(
            "/v1/superapp/transfers",
            headers=auth(parties["sender_token"]),
            json={
                "sender_username": ABEBE["username"],
                "recipient_username": SELAM["username"],
                "amount": 30.00,
                "pin": ABEBE["pin"],
            },
        )
        assert created.status_code in (200, 201), created.text

        stored = main_module.get_repo().get_payment(created.json()["payment_id"])
        assert stored is not None and stored.consent_token is not None
        claims = jwt_handler.decode_gateway_jwt(stored.consent_token)
        assert claims["consent_method"] == "superapp_pin"
        assert claims["scopes"] == ["payments:write"]

    def test_self_transfer_is_refused(
        self, client: TestClient, parties: dict[str, Any]
    ) -> None:
        response = client.post(
            "/v1/superapp/transfers",
            headers=auth(parties["sender_token"]),
            json={
                "sender_username": ABEBE["username"],
                "recipient_username": ABEBE["username"],
                "amount": 10.00,
                "pin": ABEBE["pin"],
            },
        )
        assert response.status_code >= 400
        assert "yourself" in response.text.lower()

    def test_unknown_recipient_is_refused(
        self, client: TestClient, parties: dict[str, Any]
    ) -> None:
        response = client.post(
            "/v1/superapp/transfers",
            headers=auth(parties["sender_token"]),
            json={
                "sender_username": ABEBE["username"],
                "recipient_username": "nobody_at_all",
                "amount": 10.00,
                "pin": ABEBE["pin"],
            },
        )
        assert response.status_code >= 400
        assert "no user found" in response.text.lower()

    def test_recipient_without_a_default_receiving_account_is_refused(
        self, client: TestClient, parties: dict[str, Any]
    ) -> None:
        """
        Daniel registers but links nothing, so there is nowhere to credit.
        Failing loudly beats guessing an account.
        """
        register(client, DANIEL)

        response = client.post(
            "/v1/superapp/transfers",
            headers=auth(parties["sender_token"]),
            json={
                "sender_username": ABEBE["username"],
                "recipient_username": DANIEL["username"],
                "amount": 10.00,
                "pin": ABEBE["pin"],
            },
        )
        assert response.status_code >= 400
        assert "no default receiving account" in response.text.lower()

    def test_amount_beyond_the_balance_is_refused(
        self, client: TestClient, parties: dict[str, Any]
    ) -> None:
        response = client.post(
            "/v1/superapp/transfers",
            headers=auth(parties["sender_token"]),
            json={
                "sender_username": ABEBE["username"],
                "recipient_username": SELAM["username"],
                "amount": 99_000_000.00,
                "pin": ABEBE["pin"],
            },
        )
        assert response.status_code >= 400
        assert "insufficient" in response.text.lower()


# ── 5. Settlement, ledger, and history ───────────────────────────────────────


class TestSettlementAndLedger:
    def test_completed_transfer_posts_a_balanced_ledger_entry_set(
        self, client: TestClient
    ) -> None:
        from decimal import Decimal

        sender_token = register(client, ABEBE)
        recipient_token = register(client, SELAM)
        link(client, ABEBE, sender_token, "CBE", ABEBE["cbe_account"])
        link(client, SELAM, recipient_token, "COOP", SELAM["coop_account"])

        set_default(
            client, ABEBE, sender_token,
            next(a for a in accounts_of(client, sender_token) if a["bank_id"] == "CBE")["link_id"],
            "SENDING",
        )
        set_default(
            client, SELAM, recipient_token,
            next(a for a in accounts_of(client, recipient_token) if a["bank_id"] == "COOP")["link_id"],
            "RECEIVING",
        )

        created = client.post(
            "/v1/superapp/transfers",
            headers=auth(sender_token),
            json={
                "sender_username": ABEBE["username"],
                "recipient_username": SELAM["username"],
                "amount": 500.25,
                "pin": ABEBE["pin"],
            },
        )
        assert created.status_code in (200, 201), created.text
        payment_id = created.json()["payment_id"]

        # The PIN authorised it, the bank posted the debit and credit, and
        # EUPI recorded SUCCESS in the same request. A callback is no longer
        # required to make the ledger exist.
        assert created.json()["status"] == "SUCCESS", created.text

        entries = client.get(
            f"/v1/admin/ledger/payments/{payment_id}/entries",
            headers=auth(admin_token(client)),
        )
        assert entries.status_code == 200, entries.text
        rows = entries.json()
        assert rows, "A settled transfer must produce ledger entries"

        signed = sum(
            Decimal(r["amount"]) if r["direction"] == "DEBIT" else -Decimal(r["amount"])
            for r in rows
        )
        assert signed == Decimal("0"), f"Ledger must balance to zero, got {signed}"

        # Revenue accrues against the debtor's bank, not the routed rail.
        receivables = [
            r for r in rows
            if not r["is_mirror"] and r["account_ref"].startswith("FEE_RECEIVABLE:")
        ]
        assert receivables, "A priced transfer must accrue a receivable"
        assert receivables[0]["account_ref"] == "FEE_RECEIVABLE:CBE"

        # The exact accounts that moved. The payment response omits account
        # numbers, so this is where the full resolution is finally pinned down:
        # a transfer addressed only by two usernames debited the sender's
        # default SENDING account and credited the recipient's default
        # RECEIVING account, at two different banks.
        mirror_refs = {r["account_ref"] for r in rows if r["is_mirror"]}
        assert mirror_refs == {
            f"CUSTOMER:CBE:{ABEBE['cbe_account']}",
            f"CUSTOMER:COOP:{SELAM['coop_account']}",
        }, f"unexpected accounts moved: {sorted(mirror_refs)}"

        debit_leg = next(
            r for r in rows if r["is_mirror"] and r["direction"] == "CREDIT"
        )
        assert debit_leg["account_ref"] == f"CUSTOMER:CBE:{ABEBE['cbe_account']}", (
            "Funds must leave the sender's default sending account"
        )

    def test_both_parties_see_the_transfer_with_opposite_signs(
        self, client: TestClient
    ) -> None:
        """
        One payment, two perspectives: a debit for the sender and a credit for
        the recipient, each scoped to their own linked accounts.
        """
        sender_token = login(client, ABEBE)
        recipient_token = login(client, SELAM)

        sender_history = client.get(
            "/v1/superapp/transactions", headers=auth(sender_token)
        ).json()["transactions"]
        recipient_history = client.get(
            "/v1/superapp/transactions", headers=auth(recipient_token)
        ).json()["transactions"]

        assert sender_history, "Sender must see their outgoing transfers"
        assert recipient_history, "Recipient must see their incoming transfers"

        assert any(not t["is_credit"] for t in sender_history), (
            "Sender should have at least one debit"
        )
        assert any(t["is_credit"] for t in recipient_history), (
            "Recipient should have at least one credit"
        )

    def test_history_reports_the_users_own_bank_not_the_routed_rail(
        self, client: TestClient
    ) -> None:
        """
        A history entry must name the account that moved, not the rail that
        carried the payment.

        The Smart Router may route a CBE-to-COOP transfer over any rail. Showing
        that rail here made the sender's own history disagree with the account
        the send screen said it was debiting — the user sees "COOP" for money
        that left their CBE account.
        """
        sender_token = login(client, ABEBE)
        history = client.get(
            "/v1/superapp/transactions", headers=auth(sender_token)
        ).json()["transactions"]

        outgoing = [t for t in history if not t["is_credit"]]
        assert outgoing, "Sender should have outgoing transfers to inspect"

        for transaction in outgoing:
            # The masked account and the reported bank must describe the same
            # account: last-4 of the CBE account is 2333, of the COOP one 7890.
            if transaction["masked_account"].endswith(ABEBE["cbe_account"][-4:]):
                assert transaction["bank_id"] == "CBE", (
                    f"account {transaction['masked_account']} is at CBE but the "
                    f"history reports {transaction['bank_id']}"
                )
            elif transaction["masked_account"].endswith(ABEBE["coop_account"][-4:]):
                assert transaction["bank_id"] == "COOP", (
                    f"account {transaction['masked_account']} is at COOP but the "
                    f"history reports {transaction['bank_id']}"
                )

    def test_history_never_exposes_a_full_counterparty_account_number(
        self, client: TestClient
    ) -> None:
        """Another party's full account number is enough to attempt a transfer."""
        recipient_token = login(client, SELAM)
        history = client.get(
            "/v1/superapp/transactions", headers=auth(recipient_token)
        ).json()["transactions"]

        for transaction in history:
            assert ABEBE["cbe_account"] not in transaction["counterparty_name"]
            assert ABEBE["coop_account"] not in transaction["counterparty_name"]
            assert "****" in transaction["masked_account"]

    def test_history_is_scoped_to_the_authenticated_user(
        self, client: TestClient
    ) -> None:
        """
        Daniel linked nothing, so he must see an empty list — never the
        platform's other transactions.
        """
        daniel_token = login(client, DANIEL)
        history = client.get(
            "/v1/superapp/transactions", headers=auth(daniel_token)
        ).json()
        assert history["total"] == 0
