"""
EUPI: Ethiopian Unified Payment Integration — E2E Integration Test Suite
========================================================================
Validates the full gateway lifecycle across all layers:
  1. Health & Rail Telemetry
  2. Fayda National ID eKYC Auth (Sender & Recipient)
  3. AIS Aggregated Account Balances & Transaction Statements
  4. Super App Registration & 6-Digit PIN Authentication
  5. Session Token Management & Protected Header Enforcement
  6. Account Linking with Fayda National ID Identity Verification
  7. Dashboard Bank Account Balance Synchronization
  8. P2P Transfer with Insufficient & Sufficient Balance Checks
  9. PIS Payment Verification, Order Dispatch, and Webhook Settlement
 10. Session Revocation (Logout) & Unlink Guard
"""

import sys
import json
import urllib.request
import urllib.error

BASE_URL = "http://localhost:8000"
PASS = 0
FAIL = 0


def req(method: str, path: str, body: dict | None = None, token: str | None = None) -> dict | list:
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request) as resp:
            content = resp.read().decode("utf-8")
            return json.loads(content)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        try:
            return {"_error": True, "_status": e.code, "_detail": json.loads(err_body)}
        except Exception:
            return {"_error": True, "_status": e.code, "_raw": err_body}
    except Exception as e:
        return {"_error": True, "_message": str(e)}


def check(name: str, condition: bool, info: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} — {info}")


print("=" * 70)
print("EUPI End-to-End Integration Test (with Session & Fayda Verification)")
print("=" * 70)

# ── 1. Health Check ──
print("\n── 1. Health Check ──")
r = req("GET", "/")
check("Server operational", r.get("status") == "operational", str(r))
check("Version 1.0.0", r.get("version") == "1.0.0", str(r))
check("6 bank rails registered", len(r.get("registered_rails", [])) == 6, str(r))

# ── 2. Fayda Auth — Sender (Abebe Girma, FIN 12345678901234) ──
print("\n── 2. Fayda Auth — Sender (Abebe Girma) ──")
r = req("POST", "/v1/auth/fayda", {
    "fin": "12345678901234",
    "phone_number": "+251911234567",
    "consent_scope": "accounts:read payments:write"
})
check("OTP dispatched", "session_id" in r, str(r))
sender_fayda_session = r.get("session_id", "")

r = req("POST", "/v1/auth/fayda/confirm", {
    "session_id": sender_fayda_session,
    "otp_code": "123456",
    "fin": "12345678901234"
})
check("JWT issued for sender", "access_token" in r, str(r))
sender_fayda_token = r.get("access_token", "")
check("KYC level STANDARD", r.get("kyc_level") == "STANDARD", str(r))

# ── 3. Fayda Auth — Recipient (Selamawit Bekele, FIN 23456789012345) ──
print("\n── 3. Fayda Auth — Recipient (Selamawit Bekele) ──")
r = req("POST", "/v1/auth/fayda", {
    "fin": "23456789012345",
    "phone_number": "+251922345678",
    "consent_scope": "accounts:read"
})
check("OTP dispatched", "session_id" in r, str(r))
recip_fayda_session = r.get("session_id", "")

r = req("POST", "/v1/auth/fayda/confirm", {
    "session_id": recip_fayda_session,
    "otp_code": "123456",
    "fin": "23456789012345"
})
check("JWT issued for recipient", "access_token" in r, str(r))

# ── 4. AIS — Aggregated Balances ──
print("\n── 4. AIS — Aggregated Balances ──")
r = req("GET", "/v1/accounts", token=sender_fayda_token)
check("AIS returned accounts", isinstance(r, list) and len(r) > 0, str(r))

# ── 5. Register Super App Users ──
print("\n── 5. Register Super App Users (with 6-Digit PIN, Fayda FIN Check & OTP) ──")
# Attempt registration with unregistered FIN -> Should fail
r = req("POST", "/v1/superapp/users/register", {
    "username": "fake_user_test",
    "fin": "99999999999999",  # Not in Fayda Registry!
    "full_name": "Fake Name",
    "phone_number": "+251900000000",
    "pin": "123456"
})
check("Unregistered Fayda FIN rejected (400)", r.get("_status") == 400, str(r))

# Request registration OTP with wrong phone number -> Should fail
r = req("POST", "/v1/superapp/users/register/request-otp", {
    "fin": "12345678901234",
    "phone_number": "+251999999999"  # Mismatched phone!
})
check("Mismatched Fayda phone number rejected (400)", r.get("_status") == 400, str(r))

# Request registration OTP with correct phone number (+251911234567)
r = req("POST", "/v1/superapp/users/register/request-otp", {
    "fin": "12345678901234",
    "phone_number": "+251911234567"
})
check("Registration OTP requested with verified phone", "session_id" in r, str(r))
reg_session_id = r.get("session_id", "")

r = req("POST", "/v1/superapp/users/register", {
    "username": "abebe_test_e2e",
    "fin": "12345678901234",
    "pin": "123456",
    "session_id": reg_session_id,
    "otp_code": "123456"
})
check("Sender registered with Fayda OTP verification", "username" in r, str(r))
sender_username = r.get("username", "")
check("Username formatted with @eupi", sender_username == "abebe_test_e2e@eupi", str(r))
check("Legal name autopopulated from Fayda", r.get("full_name") == "Abebe Girma Tadesse", str(r))

r = req("POST", "/v1/superapp/users/register", {
    "username": "selamawit_e2e",
    "fin": "23456789012345",
    "full_name": "Selamawit Bekele Hailu",
    "phone_number": "+251922345678",
    "pin": "654321"
})
check("Recipient registered", "username" in r, str(r))
recip_username = r.get("username", "")

# ── 6. PIN Login & Session Generation ──
print("\n── 6. PIN Login & Session Token Generation ──")
r = req("POST", "/v1/superapp/users/login", {
    "username": sender_username,
    "pin": "123456"
})
check("Sender PIN Login successful", "session_token" in r, str(r))
sender_session_token = r.get("session_token", "")

r = req("POST", "/v1/superapp/users/login", {
    "username": recip_username,
    "pin": "654321"
})
check("Recipient PIN Login successful", "session_token" in r, str(r))
recip_session_token = r.get("session_token", "")

r = req("POST", "/v1/superapp/users/login", {
    "username": sender_username,
    "pin": "999999"
})
check("Incorrect PIN rejected (401)", r.get("_status") == 401, str(r))

# ── 7. Session Protection Verification ──
print("\n── 7. Session Header Protection ──")
r = req("GET", "/v1/superapp/accounts/sync")
check("Unauthenticated sync rejected (401)", r.get("_status") == 401, str(r))

r = req("GET", "/v1/superapp/accounts/sync", token="invalid.token.here")
check("Invalid session token rejected (401)", r.get("_status") == 401, str(r))

# ── 8. Account Linking with Fayda FIN Ownership Verification ──
print("\n── 8. Account Linking with Fayda FIN Verification ──")
# Attempt linking Selamawit's account (1000987654321) to Abebe's profile -> Should fail
r = req("POST", "/v1/superapp/accounts/link", body={
    "username": sender_username,
    "bank_id": "CBE",
    "account_number": "1000987654321"  # Belongs to Selamawit Bekele Hailu!
}, token=sender_session_token)
check("Fayda FIN mismatch rejected (400)", r.get("_status") == 400, str(r))

# Link Abebe's COOP account (1000234567890) -> Should succeed
r = req("POST", "/v1/superapp/accounts/link", body={
    "username": sender_username,
    "bank_id": "COOP",
    "account_number": "1000234567890"
}, token=sender_session_token)
check("Sender COOP account linked successfully", "link_id" in r, str(r))
sender_link_id = r.get("link_id", "")
check("Auto-set as default sending", r.get("is_default_sending") is True, str(r))

# Link Selamawit's CBE account (1000987654321) under her session -> Should succeed
r = req("POST", "/v1/superapp/accounts/link", body={
    "username": recip_username,
    "bank_id": "CBE",
    "account_number": "1000987654321"
}, token=recip_session_token)
check("Recipient CBE account linked successfully", "link_id" in r, str(r))

# ── 9. Dashboard Connected Banks & Balance Synchronization ──
print("\n── 9. Dashboard Connected Banks & Balance Sync ──")
r = req("GET", "/v1/superapp/accounts/sync", token=sender_session_token)
check("Dashboard balance sync returned accounts", isinstance(r, list) and len(r) >= 1, str(r))
if isinstance(r, list) and len(r) > 0:
    check("Available balance present", "available_balance" in r[0], str(r[0]))
    check("Currency is ETB", r[0].get("currency") == "ETB", str(r[0]))

# ── 10. Link Additional Bank Accounts (Awash, Abyssinia, Berhan) ──
print("\n── 10. Link Additional Bank Accounts & Change Default ──")
r = req("POST", "/v1/superapp/accounts/link", body={
    "username": sender_username,
    "bank_id": "CBE",
    "account_number": "1000111222333"  # Belongs to Abebe Girma Tadesse
}, token=sender_session_token)
check("Sender CBE account linked", "link_id" in r, str(r))
sender_link2_id = r.get("link_id", "")

r = req("POST", "/v1/superapp/accounts/link", body={
    "username": sender_username,
    "bank_id": "AWASH",
    "account_number": "1000333444555"  # Belongs to Abebe Girma Tadesse
}, token=sender_session_token)
check("Sender Awash Bank account linked", "link_id" in r, str(r))

r = req("POST", "/v1/superapp/accounts/link", body={
    "username": sender_username,
    "bank_id": "ABYSSINIA",
    "account_number": "1000666777888"  # Belongs to Abebe Girma Tadesse
}, token=sender_session_token)
check("Sender Bank of Abyssinia account linked", "link_id" in r, str(r))

r = req("POST", "/v1/superapp/accounts/link", body={
    "username": sender_username,
    "bank_id": "BERHAN",
    "account_number": "1000111999888"  # Belongs to Abebe Girma Tadesse
}, token=sender_session_token)
check("Sender Berhan Bank account linked", "link_id" in r, str(r))

r = req("PUT", f"/v1/superapp/accounts/{sender_link2_id}/default", body={
    "username": sender_username,
    "direction": "SENDING"
}, token=sender_session_token)
check("Default sending changed", "message" in r, str(r))

# ── 11. P2P Transfer Balance Checks ──
print("\n── 11. P2P Transfer Balance Checks ──")
# Attempt transfer exceeding available balance -> Should fail
r = req("POST", "/v1/superapp/transfers", body={
    "sender_username": sender_username,
    "recipient_username": recip_username,
    "amount": "99999999.00",
    "currency": "ETB"
}, token=sender_session_token)
check("Insufficient balance rejected (400)", r.get("_status") == 400, str(r))

# Transfer with valid amount (500.00 ETB) -> Should succeed
r = req("POST", "/v1/superapp/transfers", body={
    "sender_username": sender_username,
    "recipient_username": recip_username,
    "amount": "500.00",
    "currency": "ETB",
    "remittance_info": "E2E test payment"
}, token=sender_session_token)
check("Transfer created (PENDING)", r.get("status") == "PENDING", str(r))
transfer_payment_id = r.get("payment_id", "")

# ── 12. PIS Lifecycle (Verify → Order → Callback) ──
print("\n── 12. PIS Lifecycle (Verify → Order → Callback) ──")
r = req("POST", f"/v1/payments/{transfer_payment_id}/verify", {"consent_token": sender_fayda_token})
check("Transfer verified", r.get("status") == "VERIFIED", str(r))

r = req("POST", f"/v1/payments/{transfer_payment_id}/order")
check("Transfer ordered", r.get("status") == "ORDERED", str(r))
bank_ref = r.get("bank_order_reference", "")

r = req("POST", "/v1/callbacks", {
    "payment_id": transfer_payment_id,
    "bank_order_reference": bank_ref or "TEST-REF-001",
    "confirmed": True
})
check("Payment finalized SUCCESS", r.get("final_status") == "SUCCESS", str(r))

# ── 13. Unlink Account ──
print("\n── 13. Unlink Account ──")
r = req("DELETE", f"/v1/superapp/accounts/{sender_link2_id}?username={sender_username}", token=sender_session_token)
check("Account unlinked", "message" in r, str(r))

# ── 14. Session Logout & Revocation ──
print("\n── 14. Session Logout & Token Revocation ──")
r = req("POST", "/v1/superapp/users/logout", token=sender_session_token)
check("Logout successful", "Logged out" in r.get("message", ""), str(r))

r = req("GET", "/v1/superapp/accounts/sync", token=sender_session_token)
check("Revoked session token rejected (401)", isinstance(r, dict) and r.get("_status") == 401, str(r))

# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print(f"RESULTS: {PASS} passed, {FAIL} failed out of {PASS + FAIL} checks")
print("=" * 70)

if FAIL > 0:
    sys.exit(1)
