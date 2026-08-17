"""
Port: PasswordHasherPort
Layer: 🟡 LAYER 2 — Application / Ports & Use Cases
Rule: Abstract interface only. NO concrete implementation. NO HTTP calls.

Covers every secret the platform verifies rather than reads: Super App PINs,
admin passwords, and (from the developer platform onward) client secrets.
Keeping the algorithm behind a port means a future migration — argon2 → whatever
supersedes it — touches one adapter, not every call site.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class PasswordHasherPort(ABC):
    """
    Abstract Driven Port: One-way secret hashing and verification.

    Implementations must use a salted, memory-hard, deliberately slow algorithm.
    Plain digests (SHA-256, MD5) are unacceptable — a 6-digit PIN has only
    10^6 possibilities and falls to an unsalted digest instantly.
    """

    @abstractmethod
    def hash(self, secret: str) -> str:
        """
        Hash a secret for storage.

        Args:
            secret: The plaintext secret (PIN, password, client secret).

        Returns:
            An encoded hash string carrying its own salt and parameters, safe
            to persist. Hashing the same secret twice MUST yield different
            strings.
        """
        ...

    @abstractmethod
    def verify(self, secret: str, stored_hash: str) -> bool:
        """
        Check a secret against a stored hash in constant time.

        Args:
            secret:      The plaintext secret supplied by the caller.
            stored_hash: The previously stored hash.

        Returns:
            True on match, False otherwise. Returns False rather than raising
            on a malformed or unrecognised hash — an unreadable hash is a
            failed verification, not a crash.
        """
        ...

    @abstractmethod
    def needs_rehash(self, stored_hash: str) -> bool:
        """
        Report whether a stored hash should be upgraded.

        True when the hash uses outdated parameters or a superseded algorithm
        (including legacy unsalted digests). Callers that have just verified a
        secret successfully should rehash and persist it — this is how stored
        credentials migrate forward without forcing a reset.

        Args:
            stored_hash: The previously stored hash.

        Returns:
            True if the caller should re-hash and persist the secret.
        """
        ...
