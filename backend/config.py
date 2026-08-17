"""
Application Configuration
==========================
All runtime settings sourced from environment variables.
Defaults are development-safe values — NEVER use defaults in production.

Usage:
    from backend.config import settings
    print(settings.JWT_SECRET_KEY)

Copy .env.example → .env and populate before running in any non-dev environment.
"""

from __future__ import annotations

import os

# Secrets that ship in .env.example / source defaults. Refused outside DEBUG.
_KNOWN_DEFAULT_SECRETS: frozenset[str] = frozenset({
    "kifiya-dev-secret-DO-NOT-USE-IN-PRODUCTION-change-me-now",
    "kifiya-dev-secret-CHANGE-IN-PRODUCTION",
    "changeme",
    "secret",
})

_MIN_SECRET_LENGTH = 32


class ConfigurationError(RuntimeError):
    """Raised at startup when configuration is unsafe for the target environment."""


class Settings:
    # ── JWT ───────────────────────────────────────────────────────────────────
    JWT_SECRET_KEY: str = os.getenv(
        "JWT_SECRET_KEY",
        "kifiya-dev-secret-DO-NOT-USE-IN-PRODUCTION-change-me-now",
    )
    JWT_ALGORITHM: str = "HS256"
    JWT_TOKEN_TTL_SECONDS: int = int(os.getenv("JWT_TOKEN_TTL_SECONDS", "3600"))

    # ── Admin sessions ────────────────────────────────────────────────────────
    ADMIN_SESSION_TTL_SECONDS: int = int(os.getenv("ADMIN_SESSION_TTL_SECONDS", "28800"))

    # ── PIN security ──────────────────────────────────────────────────────────
    PIN_MAX_ATTEMPTS: int = int(os.getenv("PIN_MAX_ATTEMPTS", "5"))
    PIN_LOCKOUT_SECONDS: int = int(os.getenv("PIN_LOCKOUT_SECONDS", "900"))

    # ── Identity vault ────────────────────────────────────────────────────────
    # Encryption at rest for Fayda numbers, plus the pepper for the blind index
    # that makes encrypted values searchable. Both are required outside DEBUG.
    FIN_ENCRYPTION_KEY: str = os.getenv(
        "FIN_ENCRYPTION_KEY",
        "kifiya-dev-fin-encryption-key-DO-NOT-USE-IN-PRODUCTION",
    )
    FIN_BLIND_INDEX_PEPPER: str = os.getenv(
        "FIN_BLIND_INDEX_PEPPER",
        "kifiya-dev-blind-index-pepper-DO-NOT-USE-IN-PRODUCTION",
    )

    # ── Consent ───────────────────────────────────────────────────────────────
    CONSENT_DEFAULT_TTL_DAYS: int = int(os.getenv("CONSENT_DEFAULT_TTL_DAYS", "365"))

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "sqlite:///./kifiya_gateway.db",
    )

    # ── Bank CBS API Keys ─────────────────────────────────────────────────────
    COOP_CBS_API_KEY: str = os.getenv("COOP_CBS_API_KEY", "mock-coop-key")
    CBE_CBS_API_KEY: str = os.getenv("CBE_CBS_API_KEY", "mock-cbe-key")
    WEGAGEN_CBS_API_KEY: str = os.getenv("WEGAGEN_CBS_API_KEY", "mock-wegagen-key")
    AWASH_CBS_API_KEY: str = os.getenv("AWASH_CBS_API_KEY", "mock-awash-key")
    ABYSSINIA_CBS_API_KEY: str = os.getenv("ABYSSINIA_CBS_API_KEY", "mock-abyssinia-key")
    BERHAN_CBS_API_KEY: str = os.getenv("BERHAN_CBS_API_KEY", "mock-berhan-key")

    # ── Fayda Identity API ────────────────────────────────────────────────────
    FAYDA_API_BASE_URL: str = os.getenv(
        "FAYDA_API_BASE_URL",
        "https://api.fayda.et/v1",  # Production Fayda endpoint
    )
    FAYDA_CLIENT_ID: str = os.getenv("FAYDA_CLIENT_ID", "mock-kifiya-client-id")
    FAYDA_CLIENT_SECRET: str = os.getenv("FAYDA_CLIENT_SECRET", "mock-kifiya-secret")

    # ── Smart Router ──────────────────────────────────────────────────────────
    ROUTER_UPTIME_WINDOW: int = int(os.getenv("ROUTER_UPTIME_WINDOW", "100"))  # Rolling checks
    ROUTER_WEIGHT_UPTIME: float = float(os.getenv("ROUTER_WEIGHT_UPTIME", "0.50"))
    ROUTER_WEIGHT_LATENCY: float = float(os.getenv("ROUTER_WEIGHT_LATENCY", "0.30"))
    ROUTER_WEIGHT_COST: float = float(os.getenv("ROUTER_WEIGHT_COST", "0.20"))

    # ── General ───────────────────────────────────────────────────────────────
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"
    CORS_ORIGINS: list[str] = os.getenv("CORS_ORIGINS", "*").split(",")

    # ── Startup validation ────────────────────────────────────────────────────

    def validate(self) -> None:
        """
        Refuse to start with development defaults outside DEBUG mode.

        Called at import time so misconfiguration fails before the server binds
        a port, rather than at the first request that happens to need a secret.

        Raises:
            ConfigurationError: With every problem found, not just the first.
        """
        if self.DEBUG:
            return

        problems: list[str] = []

        if self.JWT_SECRET_KEY in _KNOWN_DEFAULT_SECRETS:
            problems.append(
                "JWT_SECRET_KEY is a known development default. Generate one with:\n"
                '      python -c "import secrets; print(secrets.token_hex(32))"'
            )
        elif len(self.JWT_SECRET_KEY) < _MIN_SECRET_LENGTH:
            problems.append(
                f"JWT_SECRET_KEY is shorter than {_MIN_SECRET_LENGTH} characters "
                f"(got {len(self.JWT_SECRET_KEY)})."
            )

        # The vault protects against database compromise, so a default key
        # would make the encryption decorative — anyone with the ciphertext
        # would also have the key from the published source.
        for label, value in (
            ("FIN_ENCRYPTION_KEY", self.FIN_ENCRYPTION_KEY),
            ("FIN_BLIND_INDEX_PEPPER", self.FIN_BLIND_INDEX_PEPPER),
        ):
            if value in _KNOWN_DEFAULT_SECRETS or "DO-NOT-USE-IN-PRODUCTION" in value:
                problems.append(
                    f"{label} is a known development default. National ID "
                    f"encryption is worthless with a published key. Generate one with:\n"
                    '      python -c "import secrets; print(secrets.token_urlsafe(32))"'
                )
            elif len(value) < _MIN_SECRET_LENGTH:
                problems.append(
                    f"{label} is shorter than {_MIN_SECRET_LENGTH} characters "
                    f"(got {len(value)})."
                )

        if "*" in self.CORS_ORIGINS:
            problems.append(
                "CORS_ORIGINS is '*'. Browsers reject a wildcard origin when "
                "credentials are allowed, and it defeats CORS entirely. "
                "Set an explicit comma-separated origin list."
            )

        weight_total = (
            self.ROUTER_WEIGHT_UPTIME
            + self.ROUTER_WEIGHT_LATENCY
            + self.ROUTER_WEIGHT_COST
        )
        if abs(weight_total - 1.0) > 1e-6:
            problems.append(
                f"Smart Router weights must sum to 1.0 (got {weight_total:.4f}). "
                "Check ROUTER_WEIGHT_UPTIME / _LATENCY / _COST."
            )

        if problems:
            # ASCII only: this message is the last thing printed before the
            # process dies, and a Windows console (cp1252) mangles anything
            # else — exactly the failure mode that used to crash startup.
            raise ConfigurationError(
                "Refusing to start with an unsafe configuration (DEBUG=false):\n\n"
                + "\n\n".join(f"  - {p}" for p in problems)
                + "\n\nSee .env.example for the full variable list.\n"
            )


settings = Settings()
settings.validate()
