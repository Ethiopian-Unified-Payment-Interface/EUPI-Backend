#!/usr/bin/env python3
"""
EUPI: End-to-End Integration Test
============================================

Flow:
  1. Auth: Fayda eKYC for two users (sender + recipient)
  2. Register both as Super App users
  3. Link bank accounts for both
  4. Look up recipient profile by username
  5. Initiate P2P transfer by username
  6. Verify + Order the resulting payment
  7. Simulate bank callback → SUCCESS
  8. Also test AIS endpoints with the JWT
"""

import json
import sys
import urllib.request
import urllib.error

BASE = "http://localhost:8000"
PASS = 0
FAIL = 0


def req(method: str, path: str, body: dict | None = None, token: str | None = None) -> dict:
    """Make an HTTP request and return parsed JSON."""
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        try:
            return {"_error": True, "_status": e.code, "_detail": json.loads(error_body)}
        except Exception:
            return {"_error": True, "_status": e.code, "_detail": error_body}


def check(label: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {label}")
    else:
        FAIL += 1
        print(f"  ❌ {label} — {detail}")


# ═══════════════════════════════════════════════════════════════════════════════
print("=" * 70)
print("EUPI End-to-End Integration Test")
print("=" * 70)

# ── 1. Health Check ───────────────────────────────────────────────────────────
print("\n── 1. Health Check ──")
r = req("GET", "/")
check("Server operational", r.get("status") == "operational", str(r))
check("Version 1.0.0", r.get("version") == "1.0.0", str(r))
check("3 bank rails registered", r.get("registered_rails") == ["COOP", "CBE", "WEGAGEN"], str(r))

# ── 2. Fayda Auth — Sender (Abebe) ───────────────────────────────────────────
print("\n── 2. Fayda Auth — Sender (Abebe Girma, FIN 12345678901234) ──")
r = req("POST", "/v1/auth/fayda", {
    "fin": "12345678901234",
    "phone_number": "+251911234567",
    "consent_scope": "accounts:read,transactions:read"
})
check("OTP dispatched", "session_id" in r, str(r))
sender_session = r.get("session_id", "")

r = req("POST", "/v1/auth/fayda/confirm", {
    "session_id": sender_session,
    "otp_code": "123456",
    "fin": "12345678901234"
})
check("JWT issued for sender", "access_token" in r, str(r))
sender_token = r.get("access_token", "")
check("KYC level STANDARD", r.get("kyc_level") == "STANDARD", str(r))
check("Scopes granted", "accounts:read" in r.get("granted_scopes", []), str(r))

# ── 3. Fayda Auth — Recipient (Selamawit) ─────────────────────────────────────
print("\n── 3. Fayda Auth — Recipient (Selamawit Bekele, FIN 23456789012345) ──")
r = req("POST", "/v1/auth/fayda", {
    "fin": "23456789012345",
    "phone_number": "+251922345678",
    "consent_scope": "accounts:read"
})
check("OTP dispatched", "session_id" in r, str(r))
recip_session = r.get("session_id", "")

r = req("POST", "/v1/auth/fayda/confirm", {
    "session_id": recip_session,
    "otp_code": "123456",
    "fin": "23456789012345"
})
check("JWT issued for recipient", "access_token" in r, str(r))
recip_token = r.get("access_token", "")

# ── 4. AIS — Aggregated Balances (using sender JWT) ──────────────────────────
print("\n── 4. AIS — Aggregated Balances (Sender JWT) ──")
r = req("GET", "/v1/accounts", token=sender_token)
check("AIS returned accounts", isinstance(r, list) and len(r) > 0, f"got {type(r)}: {str(r)[:100]}")
if isinstance(r, list):
    banks_seen = {a.get("bank_id") for a in r}
    check("Accounts from COOP", "COOP" in banks_seen, str(banks_seen))
    check("Accounts from CBE", "CBE" in banks_seen, str(banks_seen))
    check("Accounts from WEGAGEN", "WEGAGEN" in banks_seen, str(banks_seen))
    # pick first account for transaction history test
    first = r[0]
    first_bank = first["bank_id"]
    first_acct = first["account_number"]

# ── 5. AIS — Transaction History ─────────────────────────────────────────────
print("\n── 5. AIS — Transaction History ──")
r = req("GET", f"/v1/accounts/{first_bank}/{first_acct}/transactions", token=sender_token)
check("Transactions returned", isinstance(r, list), f"got {type(r)}: {str(r)[:100]}")
if isinstance(r, list) and len(r) > 0:
    check("Transaction has amount", "amount" in r[0], str(r[0]))
    check("Transaction has type", "transaction_type" in r[0], str(r[0]))

# ── 6. Register Super App Users (with 6-digit PIN) ──────────────────────────
print("\n── 6. Register Super App Users (with 6-digit PIN) ──")
r = req("POST", "/v1/superapp/users/register", {
    "username": "abebe_test_e2e",
    "fin": "12345678901234",
    "full_name": "Abebe Girma Tadesse",
    "phone_number": "+251911234567",
    "pin": "123456"
})
check("Sender registered with PIN", "user_id" in r, str(r))
sender_user_id = r.get("user_id", "")
check("Username matches", r.get("username") == "abebe_test_e2e", str(r))

r = req("POST", "/v1/superapp/users/register", {
    "username": "selamawit_e2e",
    "fin": "23456789012345",
    "full_name": "Selamawit Bekele Hailu",
    "phone_number": "+251922345678",
    "pin": "654321"
})
check("Recipient registered with PIN", "user_id" in r, str(r))
recip_user_id = r.get("user_id", "")

# ── 6b. PIN Login & Authentication ────────────────────────────────────────────
print("\n── 6b. PIN Login & Authentication ──")
r = req("POST", "/v1/superapp/users/login", {
    "username": "abebe_test_e2e",
    "pin": "123456"
})
check("PIN Login successful", r.get("user_id") == sender_user_id, str(r))
check("Welcome message returned", "PIN verified" in r.get("message", ""), str(r))

r = req("POST", "/v1/superapp/users/login", {
    "username": "abebe_test_e2e",
    "pin": "999999"
})
check("Incorrect PIN rejected (401)", r.get("_status") == 401, str(r))

# ── 6c. Change PIN ────────────────────────────────────────────────────────────
print("\n── 6c. Change PIN ──")
r = req("PUT", "/v1/superapp/users/change-pin", {
    "user_id": sender_user_id,
    "current_pin": "123456",
    "new_pin": "112233"
})
check("PIN changed successfully", "message" in r, str(r))

r = req("POST", "/v1/superapp/users/login", {
    "username": "abebe_test_e2e",
    "pin": "112233"
})
check("Login with new PIN successful", r.get("user_id") == sender_user_id, str(r))

# ── 7. Duplicate Registration Guard ────────────────────────────────────────
print("\n── 7. Duplicate Registration Guard ──")
r = req("POST", "/v1/superapp/users/register", {
    "username": "abebe_test_e2e",
    "fin": "12345678901234",
    "full_name": "Abebe Girma Tadesse",
    "phone_number": "+251911234567",
    "pin": "123456"
})
check("Duplicate username rejected", r.get("_error") is True, str(r))

# ── 8. Public Profile Lookup ─────────────────────────────────────────────────
print("\n── 8. Public Profile Lookup ──")
r = req("GET", "/v1/superapp/users/profile/selamawit_e2e")
check("Profile found", r.get("username") == "selamawit_e2e", str(r))
check("Full name matches", r.get("full_name") == "Selamawit Bekele Hailu", str(r))

r = req("GET", "/v1/superapp/users/profile/nonexistent_user_xyz")
check("Unknown user returns 404", r.get("_status") == 404, str(r))

# ── 9. Link Bank Accounts ────────────────────────────────────────────────────
print("\n── 9. Link Bank Accounts ──")
r = req("POST", "/v1/superapp/accounts/link", {
    "user_id": sender_user_id,
    "bank_id": "COOP",
    "account_number": "1000234567890"
})
check("Sender COOP account linked", "link_id" in r, str(r))
sender_link_id = r.get("link_id", "")
check("Auto-set as default sending", r.get("is_default_sending") is True, str(r))
check("Auto-set as default receiving", r.get("is_default_receiving") is True, str(r))

r = req("POST", "/v1/superapp/accounts/link", {
    "user_id": recip_user_id,
    "bank_id": "CBE",
    "account_number": "1000987654321"
})
check("Recipient CBE account linked", "link_id" in r, str(r))
recip_link_id = r.get("link_id", "")

# ── 10. List Linked Accounts ─────────────────────────────────────────────────
print("\n── 10. List Linked Accounts ──")
r = req("GET", f"/v1/superapp/accounts/user/{sender_user_id}")
check("Sender has linked accounts", isinstance(r, list) and len(r) >= 1, str(r))

# ── 11. Link Second Account + Set Default ─────────────────────────────────────
print("\n── 11. Link Second Account + Change Default ──")
r = req("POST", "/v1/superapp/accounts/link", {
    "user_id": sender_user_id,
    "bank_id": "CBE",
    "account_number": "1000111222333"
})
check("Sender CBE account linked", "link_id" in r, str(r))
sender_link2_id = r.get("link_id", "")

r = req("PUT", f"/v1/superapp/accounts/{sender_link2_id}/default", {
    "user_id": sender_user_id,
    "direction": "SENDING"
})
check("Default sending changed", "message" in r, str(r))

# ── 12. P2P Transfer by Username ──────────────────────────────────────────────
print("\n── 12. P2P Transfer by Username ──")
r = req("POST", "/v1/superapp/transfers", {
    "sender_user_id": sender_user_id,
    "recipient_username": "selamawit_e2e",
    "amount": "500.00",
    "currency": "ETB",
    "remittance_info": "E2E test payment"
})
check("Transfer created (PENDING)", r.get("status") == "PENDING", str(r))
transfer_payment_id = r.get("payment_id", "")
check("Payment ID assigned", transfer_payment_id.startswith("PAY-"), str(r))
check("Amount is 500", str(r.get("amount")) in ("500.00", "500"), str(r))

# ── 13. PIS — Verify Transfer ────────────────────────────────────────────────
print("\n── 13. PIS — Verify Transfer ──")
r = req("POST", f"/v1/payments/{transfer_payment_id}/verify", {
    "consent_token": sender_token
})
check("Transfer verified", r.get("status") == "VERIFIED", str(r))

# ── 14. PIS — Order Transfer ─────────────────────────────────────────────────
print("\n── 14. PIS — Order Transfer ──")
r = req("POST", f"/v1/payments/{transfer_payment_id}/order")
check("Transfer ordered", r.get("status") == "ORDERED", str(r))
bank_ref = r.get("bank_order_reference", "")
check("Bank reference assigned", bank_ref != "" and bank_ref is not None, str(r))

# ── 15. Webhook Callback — SUCCESS ───────────────────────────────────────────
print("\n── 15. Webhook Callback — Finalize as SUCCESS ──")
r = req("POST", "/v1/callbacks", {
    "payment_id": transfer_payment_id,
    "bank_order_reference": bank_ref or "TEST-REF-001",
    "confirmed": True,
    "failure_reason": None
})
check("Payment finalized SUCCESS", r.get("final_status") == "SUCCESS", str(r))

# ── 16. PIS — Verify Final State ─────────────────────────────────────────────
print("\n── 16. PIS — Verify Final State ──")
r = req("GET", f"/v1/payments/{transfer_payment_id}")
check("Payment status is SUCCESS", r.get("status") == "SUCCESS", str(r))

# ── 17. Unlink Account ───────────────────────────────────────────────────────
print("\n── 17. Unlink Account ──")
r = req("DELETE", f"/v1/superapp/accounts/{sender_link2_id}?user_id={sender_user_id}")
check("Account unlinked", "message" in r, str(r))

r = req("GET", f"/v1/superapp/accounts/user/{sender_user_id}")
check("Only 1 account remaining", isinstance(r, list) and len(r) == 1, f"count={len(r) if isinstance(r, list) else r}")

# ── 18. Direct PIS Flow (non-super-app) ──────────────────────────────────────
print("\n── 18. Direct PIS Flow (standard Open Banking) ──")
import uuid
e2e_id = f"E2E-TEST-{uuid.uuid4().hex[:8].upper()}"
r = req("POST", "/v1/payments/initiate", body={
    "debtor_account_number": "1000234567890",
    "debtor_bank_id": "COOP",
    "creditor_account_number": "1000987654321",
    "creditor_bank_id": "CBE",
    "creditor_name": "Selam Tesfaye",
    "amount": "1000.00",
    "currency": "ETB",
    "end_to_end_id": e2e_id,
}, token=sender_token)
check("PIS payment initiated", r.get("status") == "PENDING", str(r))
pis_id = r.get("payment_id", "")

r = req("POST", f"/v1/payments/{pis_id}/verify", {"consent_token": sender_token})
check("PIS payment verified", r.get("status") == "VERIFIED", str(r))

r = req("POST", f"/v1/payments/{pis_id}/order")
check("PIS payment ordered", r.get("status") == "ORDERED", str(r))

r = req("POST", f"/v1/payments/{pis_id}/cancel", {"reason": "Testing cancellation"})
check("Terminal payment cancel rejected", r.get("_error") is True, str(r))

# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print(f"RESULTS: {PASS} passed, {FAIL} failed out of {PASS + FAIL} checks")
print("=" * 70)

if FAIL > 0:
    sys.exit(1)
