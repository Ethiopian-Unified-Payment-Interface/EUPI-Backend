"""
Fernet Identity Vault — FIN Encryption Adapter
==============================================
Layer: 🔴 LAYER 3 — Infrastructure / Auth

Implements IdentityVaultPort with Fernet (AES-128-CBC + HMAC-SHA256) for
encryption and HMAC-SHA256 for the blind index.

Key management
--------------
Both secrets come from the environment and are required outside DEBUG. In
production they belong in a KMS or secrets manager, not a .env file — the
threat this defends against is database compromise, and a key sitting next to
the database on the same host defends against nothing.

Rotation is not implemented. Doing it properly needs a key-version column and a
re-encryption pass, which belongs with the Alembic work rather than here.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging

from cryptography.fernet import Fernet, InvalidToken

from backend.application.ports.vault_port import IdentityVaultPort
from backend.config import settings

logger = logging.getLogger(__name__)


class FernetIdentityVault(IdentityVaultPort):
    """
    Fernet-based implementation of IdentityVaultPort.

    Fernet is authenticated encryption: tampered ciphertext fails to decrypt
    rather than silently returning corrupt data. That matters here — a FIN that
    decrypts to the wrong digits is worse than one that fails loudly.
    """

    def __init__(
        self,
        encryption_key: str | None = None,
        blind_index_pepper: str | None = None,
    ) -> None:
        """
        Args:
            encryption_key:     urlsafe-base64 32-byte Fernet key. Defaults to
                                settings.FIN_ENCRYPTION_KEY.
            blind_index_pepper: Secret for the blind index HMAC. Defaults to
                                settings.FIN_BLIND_INDEX_PEPPER.
        """
        key = encryption_key or settings.FIN_ENCRYPTION_KEY
        pepper = blind_index_pepper or settings.FIN_BLIND_INDEX_PEPPER

        self._fernet = Fernet(self._normalise_key(key))
        self._pepper = pepper.encode("utf-8")

    @staticmethod
    def _normalise_key(key: str) -> bytes:
        """
        Coerce a configured secret into a valid Fernet key.

        A Fernet key must be exactly 32 urlsafe-base64 bytes. Rather than force
        operators to generate one in a specific format — and rather than crash
        on a key that is merely the wrong shape — an arbitrary secret is
        stretched through SHA-256 into a valid key deterministically.

        A key already in Fernet's own format is used as-is, so an explicitly
        generated key is never silently transformed into a different one.
        """
        raw = key.encode("utf-8")
        try:
            if len(base64.urlsafe_b64decode(raw)) == 32:
                return raw
        except Exception:  # noqa: BLE001 — not base64; fall through to derivation
            pass
        return base64.urlsafe_b64encode(hashlib.sha256(raw).digest())

    def encrypt(self, value: str) -> str:
        """Encrypt a FIN. Randomised, so the same FIN yields different ciphertext."""
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        """
        Recover a FIN.

        Raises:
            ValueError: On corrupt ciphertext or a key mismatch — never a
                        silent fallback, since returning a wrong national ID
                        would be worse than failing.
        """
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            logger.error("Failed to decrypt a vaulted FIN — corrupt data or wrong key.")
            raise ValueError(
                "Could not decrypt the stored identity number. The encryption "
                "key may have changed."
            ) from exc

    def blind_index(self, value: str) -> str:
        """
        Keyed digest for equality lookups.

        Normalises whitespace first so that " 123 " and "123" resolve to the
        same account — otherwise a stray space creates a duplicate identity
        that the uniqueness constraint would not catch.
        """
        normalised = value.strip()
        return hmac.new(self._pepper, normalised.encode("utf-8"), hashlib.sha256).hexdigest()
