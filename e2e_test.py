"""
EUPI: Ethiopian Unified Payment Integration — E2E Integration Test Suite
========================================================================
Strictly validates the full gateway lifecycle across all layers:
  1. Health & Rail Telemetry (6 Commercial Ethiopian Bank Adapters)
  2. Fayda National ID eKYC Auth (Sender & Recipient + Invalid OTP Guards)
  3. AIS Aggregated Account Balances
  4. 3-Step Super App Registration (Request OTP -> Verify OTP -> Complete)
  5. Registration Edge Cases (Invalid OTP, Replay Attack, Tampered Token, Duplicate FIN, Duplicate Username, PIN Format)
  6. PIN Authentication, Public Profile Lookup & PIN Change Security Flow
  7. Session Token Management & Protected Header Enforcement
  8. Account Linking with Fayda FIN Ownership Verification & Cross-User Security Guards
  9. Dashboard Bank Account Balance Synchronization
 10. Multi-Bank Account Linking (COOP, CBE, Awash, Abyssinia, Wegagen, Berhan) & Default Selection
 11. P2P Transfer Strict Guards (Self-Transfer, Non-Existent User, No Default Account, Impersonation Guard, Balance Guard)
 12. PIS Lifecycle (Verify → Order → Callback Settlement)
 13. Unlink Account & Unlink Security Guards
 14. Session Revocation (Logout) & Post-Logout Access Guard
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


print("=" * 75)
print("EUPI End-to-End Integration Test Suite (Strict Verification & Edge Cases)")
print("=" * 75)

# ── 1. Health Check ──
print("\n── 1. Health Check ──")
r = req("GET", "/")
check("Server operational", r.get("status") == "operational", str(r))
check("Version 1.0.0", r.get("version") == "1.0.0", str(r))
check("6 bank rails registered", len(r.get("registered_rails", [])) == 6, str(r))
check("COOP rail present", "COOP" in r.get("registered_rails", []), str(r))
check("CBE rail present", "CBE" in r.get("registered_rails", []), str(r))
check("AWASH rail present", "AWASH" in r.get("registered_rails", []), str(r))
check("ABYSSINIA rail present", "ABYSSINIA" in r.get("registered_rails", []), str(r))
check("BERHAN rail present", "BERHAN" in r.get("registered_rails", []), str(r))

# ── 2. Fayda Auth & OTP Strict Guards (Abebe Girma, FIN 12345678901234) ──
print("\n── 2. Fayda Auth & OTP Guards ──")
r = req("POST", "/v1/auth/fayda", {
    "fin": "12345678901234",
    "phone_number": "+251911234567",
    "consent_scope": "accounts:read payments:write"
})
check("OTP dispatched for Abebe", "session_id" in r, str(r))
sender_fayda_session = r.get("session_id", "")

# Invalid OTP rejection
r = req("POST", "/v1/auth/fayda/confirm", {
    "session_id": sender_fayda_session,
    "otp_code": "999999",  # Invalid OTP!
    "fin": "12345678901234"
})
check("Invalid OTP rejected (400/401)", r.get("_status") in (400, 401), str(r))

# Re-request OTP for sender
r = req("POST", "/v1/auth/fayda", {
    "fin": "12345678901234",
    "phone_number": "+251911234567",
    "consent_scope": "accounts:read payments:write"
})
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
print("\n── 3. Fayda Auth — Recipient ──")
r = req("POST", "/v1/auth/fayda", {
    "fin": "23456789012345",
    "phone_number": "+251922345678",
    "consent_scope": "accounts:read"
})
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

# ── 5. Register Super App Users & Strict Registration Guards ──
print("\n── 5. 3-Step User Registration & Security Guards ──")
# Unregistered FIN
r = req("POST", "/v1/superapp/users/register/request-otp", {
    "fin": "99999999999999",
    "phone_number": "+251911234567"
})
check("Unregistered Fayda FIN rejected (400)", r.get("_status") == 400, str(r))

# Mismatched phone
r = req("POST", "/v1/superapp/users/register/request-otp", {
    "fin": "12345678901234",
    "phone_number": "+251999999999"
})
check("Mismatched Fayda phone number rejected (400)", r.get("_status") == 400, str(r))

# Step 1: Request OTP
r = req("POST", "/v1/superapp/users/register/request-otp", {
    "fin": "12345678901234",
    "phone_number": "+251911234567"
})
check("Step 1: Registration OTP requested", "session_id" in r, str(r))
reg_session_id = r.get("session_id", "")

# Step 2: Verify OTP
r = req("POST", "/v1/superapp/users/register/verify-otp", {
    "session_id": reg_session_id,
    "otp_code": "123456"
})
check("Step 2: Registration OTP verified -> token issued", "registration_token" in r, str(r))
reg_token = r.get("registration_token", "")

# Single-use OTP session check (Replay attack guard)
r = req("POST", "/v1/superapp/users/register/verify-otp", {
    "session_id": reg_session_id,
    "otp_code": "123456"
})
check("OTP session replay rejected (400)", r.get("_status") == 400, str(r))

# Step 3: Complete with invalid token
r = req("POST", "/v1/superapp/users/register/complete", {
    "registration_token": "invalid.jwt.token",
    "username": "abebe_test_e2e",
    "pin": "123456"
})
check("Tampered registration_token rejected (400)", r.get("_status") == 400, str(r))

# Step 3: Complete with invalid PIN length
r = req("POST", "/v1/superapp/users/register/complete", {
    "registration_token": reg_token,
    "username": "abebe_test_e2e",
    "pin": "1234"  # Only 4 digits!
})
check("Non 6-digit PIN rejected (400/422)", r.get("_status") in (400, 422), str(r))

# Step 3: Complete valid registration
r = req("POST", "/v1/superapp/users/register/complete", {
    "registration_token": reg_token,
    "username": "abebe_test_e2e",
    "pin": "123456"
})
check("Step 3: Registration completed cleanly", "username" in r, str(r))
sender_username = r.get("username", "abebe_test_e2e@eupi")
check("Username auto-appended @eupi", sender_username == "abebe_test_e2e@eupi", str(r))

# Duplicate FIN registration attempt guard
r = req("POST", "/v1/superapp/users/register/request-otp", {
    "fin": "12345678901234",
    "phone_number": "+251911234567"
})
check("Duplicate FIN registration rejected (400)", r.get("_status") == 400, str(r))

# Register Recipient (Selamawit)
r = req("POST", "/v1/superapp/users/register/request-otp", {
    "fin": "23456789012345",
    "phone_number": "+251922345678"
})
recip_session_id = r.get("session_id", "")

r = req("POST", "/v1/superapp/users/register/verify-otp", {
    "session_id": recip_session_id,
    "otp_code": "123456"
})
recip_reg_token = r.get("registration_token", "")

# Duplicate username attempt guard (try using abebe_test_e2e)
r = req("POST", "/v1/superapp/users/register/complete", {
    "registration_token": recip_reg_token,
    "username": "abebe_test_e2e",  # Username already taken!
    "pin": "654321"
})
check("Duplicate username handle rejected (400)", r.get("_status") == 400, str(r))

# Complete valid Recipient registration
r = req("POST", "/v1/superapp/users/register/complete", {
    "registration_token": recip_reg_token,
    "username": "selamawit_e2e",
    "pin": "654321"
})
check("Recipient registered cleanly", "username" in r, str(r))
recip_username = r.get("username", "selamawit_e2e@eupi")

# Register 3rd user without bank accounts (Daniel) to test no default account guard
r = req("POST", "/v1/superapp/users/register/request-otp", {
    "fin": "21872187218777",
    "phone_number": "+251904267039"
})
dan_session_id = r.get("session_id", "")

r = req("POST", "/v1/superapp/users/register/verify-otp", {
    "session_id": dan_session_id,
    "otp_code": "123456"
})
dan_reg_token = r.get("registration_token", "")

r = req("POST", "/v1/superapp/users/register/complete", {
    "registration_token": dan_reg_token,
    "username": "daniel_e2e",
    "pin": "112233"
})
dan_username = r.get("username", "daniel_e2e@eupi")

# ── 6. PIN Login, Profile Lookup & PIN Change ──
print("\n── 6. PIN Login, Profile Lookup & PIN Change ──")
# Login with base handle without @eupi
r = req("POST", "/v1/superapp/users/login", {
    "username": "abebe_test_e2e",
    "pin": "123456"
})
check("Sender PIN Login successful (without @eupi)", "session_token" in r, str(r))
sender_session_token = r.get("session_token", "")

r = req("POST", "/v1/superapp/users/login", {
    "username": "selamawit_e2e",
    "pin": "654321"
})
check("Recipient PIN Login successful", "session_token" in r, str(r))
recip_session_token = r.get("session_token", "")

r = req("POST", "/v1/superapp/users/login", {
    "username": "daniel_e2e",
    "pin": "112233"
})
check("Daniel PIN Login successful", "session_token" in r, str(r))
dan_session_token = r.get("session_token", "")

# Incorrect PIN rejection
r = req("POST", "/v1/superapp/users/login", {
    "username": "abebe_test_e2e",
    "pin": "999999"
})
check("Incorrect PIN rejected (401)", r.get("_status") == 401, str(r))

# Public profile lookup (without @eupi)
r = req("GET", "/v1/superapp/users/profile/abebe_test_e2e")
check("Public profile lookup succeeded", r.get("full_name") == "Abebe Girma Tadesse", str(r))

# Public profile lookup non-existent user
r = req("GET", "/v1/superapp/users/profile/nonexistent_user_xyz")
check("Non-existent profile lookup returned 404", r.get("_status") == 404, str(r))

# Change PIN Flow for Daniel
r = req("PUT", "/v1/superapp/users/change-pin", body={
    "username": "daniel_e2e",
    "current_pin": "112233",
    "new_pin": "998877"
}, token=dan_session_token)
check("PIN changed successfully", "message" in r, str(r))

# Verify old PIN fails
r = req("POST", "/v1/superapp/users/login", {
    "username": "daniel_e2e",
    "pin": "112233"
})
check("Old PIN rejected after PIN change (401)", r.get("_status") == 401, str(r))

# Verify new PIN works
r = req("POST", "/v1/superapp/users/login", {
    "username": "daniel_e2e",
    "pin": "998877"
})
check("New PIN login succeeded (200)", "session_token" in r, str(r))

# ── 7. Session Protection Verification ──
print("\n── 7. Session Header Protection ──")
r = req("GET", "/v1/superapp/accounts/sync")
check("Unauthenticated sync rejected (401)", r.get("_status") == 401, str(r))

r = req("GET", "/v1/superapp/accounts/sync", token="invalid.token.here")
check("Invalid session token rejected (401)", r.get("_status") == 401, str(r))

# ── 8. Account Linking & Security Guards ──
print("\n── 8. Account Linking & Ownership Verification ──")
# Link attempt with invalid/unsupported bank code
r = req("POST", "/v1/superapp/accounts/link", body={
    "username": "abebe_test_e2e",
    "bank_id": "UNSUPPORTED_BANK",
    "account_number": "1000234567890"
}, token=sender_session_token)
check("Unsupported bank code rejected (400)", r.get("_status") == 400, str(r))

# Attempt linking Selamawit's account (1000987654321) to Abebe's profile -> Should fail
r = req("POST", "/v1/superapp/accounts/link", body={
    "username": "abebe_test_e2e",
    "bank_id": "CBE",
    "account_number": "1000987654321"  # Belongs to Selamawit!
}, token=sender_session_token)
check("Fayda FIN ownership mismatch rejected (400)", r.get("_status") == 400, str(r))

# Impersonation guard: Abebe tries to link account specifying username="selamawit_e2e"
r = req("POST", "/v1/superapp/accounts/link", body={
    "username": "selamawit_e2e",
    "bank_id": "CBE",
    "account_number": "1000987654321"
}, token=sender_session_token)
check("Linking account for another user rejected (403)", r.get("_status") == 403, str(r))

# Link Abebe's COOP account (1000234567890) -> Should succeed
r = req("POST", "/v1/superapp/accounts/link", body={
    "username": "abebe_test_e2e",  # Base handle without @eupi
    "bank_id": "COOP",
    "account_number": "1000234567890"
}, token=sender_session_token)
check("Sender COOP account linked successfully", "link_id" in r, str(r))
sender_link_id = r.get("link_id", "")
check("Auto-set as default sending", r.get("is_default_sending") is True, str(r))

# Link Selamawit's CBE account (1000987654321) under her session
r = req("POST", "/v1/superapp/accounts/link", body={
    "username": "selamawit_e2e",
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

# ── 10. Multi-Bank Account Linking (Awash, Abyssinia, Berhan) & Default Selection ──
print("\n── 10. Multi-Bank Account Linking & Default Selection ──")
r = req("POST", "/v1/superapp/accounts/link", body={
    "username": "abebe_test_e2e",
    "bank_id": "CBE",
    "account_number": "1000111222333"
}, token=sender_session_token)
check("Sender CBE account linked", "link_id" in r, str(r))
sender_link2_id = r.get("link_id", "")

r = req("POST", "/v1/superapp/accounts/link", body={
    "username": "abebe_test_e2e",
    "bank_id": "AWASH",
    "account_number": "1000333444555"
}, token=sender_session_token)
check("Sender Awash Bank account linked", "link_id" in r, str(r))

r = req("POST", "/v1/superapp/accounts/link", body={
    "username": "abebe_test_e2e",
    "bank_id": "ABYSSINIA",
    "account_number": "1000666777888"
}, token=sender_session_token)
check("Sender Bank of Abyssinia account linked", "link_id" in r, str(r))

r = req("POST", "/v1/superapp/accounts/link", body={
    "username": "abebe_test_e2e",
    "bank_id": "BERHAN",
    "account_number": "1000111999888"
}, token=sender_session_token)
check("Sender Berhan Bank account linked", "link_id" in r, str(r))

# Impersonation guard on setting default account
r = req("PUT", f"/v1/superapp/accounts/{sender_link2_id}/default", body={
    "username": "selamawit_e2e",
    "direction": "SENDING"
}, token=sender_session_token)
check("Setting default for another user rejected (403)", r.get("_status") == 403, str(r))

# Valid set default sending account
r = req("PUT", f"/v1/superapp/accounts/{sender_link2_id}/default", body={
    "username": "abebe_test_e2e",
    "direction": "SENDING"
}, token=sender_session_token)
check("Default sending account updated", "message" in r, str(r))

# Query user linked accounts list endpoint
r = req("GET", "/v1/superapp/accounts/user/abebe_test_e2e", token=sender_session_token)
check("List user linked accounts returned 5 links", isinstance(r, list) and len(r) == 5, str(r))

# ── 11. P2P Transfer Strict Guards ──
print("\n── 11. P2P Transfer Strict Guards ──")
# Self-transfer guard
r = req("POST", "/v1/superapp/transfers", body={
    "sender_username": "abebe_test_e2e",
    "recipient_username": "abebe_test_e2e",
    "amount": "100.00",
    "currency": "ETB"
}, token=sender_session_token)
check("Self-transfer rejected (400)", r.get("_status") == 400, str(r))

# Non-existent recipient guard
r = req("POST", "/v1/superapp/transfers", body={
    "sender_username": "abebe_test_e2e",
    "recipient_username": "nonexistent_recipient_xyz",
    "amount": "100.00",
    "currency": "ETB"
}, token=sender_session_token)
check("Non-existent recipient rejected (400)", r.get("_status") == 400, str(r))

# Recipient without default account guard (Daniel has no linked accounts)
r = req("POST", "/v1/superapp/transfers", body={
    "sender_username": "abebe_test_e2e",
    "recipient_username": "daniel_e2e",
    "amount": "100.00",
    "currency": "ETB"
}, token=sender_session_token)
check("Recipient without linked account rejected (400)", r.get("_status") == 400, str(r))

# Transfer impersonation guard (Abebe tries to initiate transfer with sender_username="selamawit_e2e")
r = req("POST", "/v1/superapp/transfers", body={
    "sender_username": "selamawit_e2e",
    "recipient_username": "abebe_test_e2e",
    "amount": "100.00",
    "currency": "ETB"
}, token=sender_session_token)
check("Transfer impersonation rejected (403)", r.get("_status") == 403, str(r))

# Exceeding available balance guard
r = req("POST", "/v1/superapp/transfers", body={
    "sender_username": "abebe_test_e2e",
    "recipient_username": "selamawit_e2e",
    "amount": "99999999.00",
    "currency": "ETB"
}, token=sender_session_token)
check("Insufficient balance rejected (400)", r.get("_status") == 400, str(r))

# Valid transfer creation (500.00 ETB)
r = req("POST", "/v1/superapp/transfers", body={
    "sender_username": "abebe_test_e2e",
    "recipient_username": "selamawit_e2e",
    "amount": "500.00",
    "currency": "ETB",
    "remittance_info": "Dinner split payment"
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

# ── 13. Unlink Account & Unlink Guards ──
print("\n── 13. Unlink Account & Security Guards ──")
# Impersonation guard: Abebe tries to unlink specifying username="selamawit_e2e"
r = req("DELETE", f"/v1/superapp/accounts/{sender_link2_id}?username=selamawit_e2e", token=sender_session_token)
check("Unlinking another user's account rejected (403)", r.get("_status") == 403, str(r))

# Non-existent link ID guard
r = req("DELETE", "/v1/superapp/accounts/nonexistent_link_999?username=abebe_test_e2e", token=sender_session_token)
check("Unlinking non-existent link ID returned 404", r.get("_status") == 404, str(r))

# Valid unlink
r = req("DELETE", f"/v1/superapp/accounts/{sender_link2_id}?username=abebe_test_e2e", token=sender_session_token)
check("Account unlinked successfully", "message" in r, str(r))

# ── 14. Session Logout & Revocation ──
print("\n── 14. Session Logout & Token Revocation ──")
r = req("POST", "/v1/superapp/users/logout", token=sender_session_token)
check("Logout successful", "Logged out" in r.get("message", ""), str(r))

r = req("GET", "/v1/superapp/accounts/sync", token=sender_session_token)
check("Revoked session token rejected (401)", isinstance(r, dict) and r.get("_status") == 401, str(r))

# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 75)
print(f"RESULTS: {PASS} passed, {FAIL} failed out of {PASS + FAIL} checks")
print("=" * 75)

if FAIL > 0:
    sys.exit(1)
