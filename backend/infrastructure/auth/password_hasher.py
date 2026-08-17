"""
Argon2 Password Hasher — Secret Hashing Adapter
===============================================
Layer: 🔴 LAYER 3 — Infrastructure / Auth

Implements PasswordHasherPort using argon2id, the Password Hashing Competition
winner and the current OWASP recommendation.

Legacy migration
----------------
Super App PINs were originally stored as unsalted SHA-256 (64 hex characters).
That is not a survivable scheme for a 6-digit PIN: the entire 10^6 keyspace can
be precomputed in well under a second, and identical PINs produced identical
hashes across users.

`verify()` therefore still accepts a legacy digest so existing accounts keep
working, and `needs_rehash()` reports True for every one of them. Call sites
that verify successfully must rehash and persist — see
`UserRegistrationService.verify_pin`. Once no legacy hashes remain in the
database, `_LEGACY_SHA256_PATTERN` and its branch can be deleted.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re

from argon2 import PasswordHasher as _Argon2PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from backend.application.ports.password_hasher_port import PasswordHasherPort

logger = logging.getLogger(__name__)

# Exactly 64 lowercase hex characters — the shape of the retired SHA-256 scheme.
_LEGACY_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class Argon2PasswordHasher(PasswordHasherPort):
    """
    argon2id hasher with OWASP-aligned defaults.

    Defaults (19 MiB memory, 2 passes, 1 lane) follow the OWASP Password
    Storage Cheat Sheet. They are deliberately not configurable via environment
    variables: weakening them silently is a far more likely accident than
    needing to tune them, and `needs_rehash()` handles upgrades when they change.
    """

    def __init__(self) -> None:
        self._hasher = _Argon2PasswordHasher(
            time_cost=2,
            memory_cost=19 * 1024,  # 19 MiB
            parallelism=1,
            hash_len=32,
            salt_len=16,
        )

    def hash(self, secret: str) -> str:
        """Hash a secret with a fresh random salt."""
        return self._hasher.hash(secret)

    def verify(self, secret: str, stored_hash: str) -> bool:
        """
        Verify a secret against an argon2 or legacy SHA-256 hash.

        Never raises: any malformed, unrecognised, or mismatched hash is a
        failed verification.
        """
        if not stored_hash:
            return False

        if _LEGACY_SHA256_PATTERN.match(stored_hash):
            return self._verify_legacy_sha256(secret, stored_hash)

        try:
            return self._hasher.verify(stored_hash, secret)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, stored_hash: str) -> bool:
        """
        True for legacy digests and for argon2 hashes with outdated parameters.
        """
        if not stored_hash:
            return False

        if _LEGACY_SHA256_PATTERN.match(stored_hash):
            return True

        try:
            return self._hasher.check_needs_rehash(stored_hash)
        except InvalidHashError:
            # Unreadable hash — treat as needing replacement rather than crashing.
            return True

    @staticmethod
    def _verify_legacy_sha256(secret: str, stored_hash: str) -> bool:
        """
        Constant-time comparison against the retired unsalted SHA-256 scheme.

        Retained only so existing accounts can authenticate once and be migrated
        forward on the spot. Never used to produce a new hash.
        """
        logger.info("Verifying against a legacy PIN hash; caller should rehash.")
        candidate = hashlib.sha256(secret.encode()).hexdigest()
        return hmac.compare_digest(candidate, stored_hash)
