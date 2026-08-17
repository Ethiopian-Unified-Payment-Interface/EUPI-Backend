"""
Port: IdentityVaultPort
Layer: 🟡 LAYER 2 — Application / Ports & Use Cases
Rule: Abstract interface only. NO concrete implementation. NO HTTP calls.

Encryption at rest for national identity numbers.

The blind index
---------------
Encrypting the FIN alone would break the one query the system depends on:
"does an account already exist for this national ID?" Authenticated encryption
produces different ciphertext every time, so `WHERE fin_encrypted = ?` can never
match.

The standard answer is a **blind index** — a keyed, deterministic hash stored
alongside the ciphertext and indexed. Equality lookups run against the index;
the ciphertext is only ever decrypted when a caller has a specific, audited
reason to see the value.

It must be keyed (HMAC), not a bare hash. A plain SHA-256 of a 14-digit FIN is
reversible by brute force in seconds — the keyspace is only 10^14 and an
attacker with the database could enumerate it offline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class IdentityVaultPort(ABC):
    """
    Abstract Driven Port: Reversible encryption plus deterministic indexing
    for national identity numbers.
    """

    @abstractmethod
    def encrypt(self, value: str) -> str:
        """
        Encrypt a national identity number for storage.

        Args:
            value: The plaintext FIN.

        Returns:
            Ciphertext safe to persist. Encrypting the same value twice MUST
            produce different ciphertext.
        """
        ...

    @abstractmethod
    def decrypt(self, ciphertext: str) -> str:
        """
        Recover a national identity number.

        Call sites are deliberately few: registration deduplication and the
        restricted `identity:read:fin` scope. Anything else should be using a
        pseudonym instead.

        Args:
            ciphertext: Previously encrypted value.

        Returns:
            The plaintext FIN.

        Raises:
            ValueError: If the ciphertext is corrupt or was encrypted under a
                        different key.
        """
        ...

    @abstractmethod
    def blind_index(self, value: str) -> str:
        """
        Deterministic keyed digest for equality lookups.

        The same input always yields the same output, so this column can be
        indexed and queried — while remaining infeasible to reverse without the
        key.

        Args:
            value: The plaintext FIN.

        Returns:
            Hex digest suitable for an indexed, unique column.
        """
        ...
