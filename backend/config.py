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

_CBS_MODE_SIMULATED = "simulated"
_CBS_MODE_LIVE = "live"
_CBS_MODES = frozenset({_CBS_MODE_SIMULATED, _CBS_MODE_LIVE})


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

    # ── Core Banking mode ─────────────────────────────────────────────────────
    # "simulated" runs every rail against the in-database simulated core banking
    # system: real balances, real atomic debit/credit, real settlement. No live
    # bank is contacted. "live" is reserved for adapters backed by an actual CBS
    # and is rejected until one exists, so the mode can never silently degrade
    # into pretending a transfer happened.
    CBS_MODE: str = os.getenv("CBS_MODE", "simulated").strip().lower()

    # Simulated funds are not money. Running the simulator outside DEBUG is a
    # legitimate thing to do — a shared sandbox is exactly that — but it has to
    # be a decision someone made on purpose, not a default that survived into an
    # environment where a user could mistake the balances for their own.
    ALLOW_SIMULATED_CBS: bool = os.getenv("ALLOW_SIMULATED_CBS", "false").lower() == "true"

    # Delay between the bank accepting a debit order and confirming settlement.
    # Real settlement is asynchronous; collapsing it to zero would hide every
    # bug that only appears while a payment is in flight.
    CBS_SETTLEMENT_DELAY_SECONDS: float = float(
        os.getenv("CBS_SETTLEMENT_DELAY_SECONDS", "3")
    )
    CBS_SETTLEMENT_POLL_INTERVAL_SECONDS: float = float(
        os.getenv("CBS_SETTLEMENT_POLL_INTERVAL_SECONDS", "2")
    )
    # Probability that the simulated bank rejects a transfer at settlement.
    # Zero by default so demos are predictable; raise it to exercise the FAILED
    # path and the reversal it triggers.
    CBS_SETTLEMENT_FAILURE_RATE: float = float(
        os.getenv("CBS_SETTLEMENT_FAILURE_RATE", "0")
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

    @property
    def SIMULATED_CBS(self) -> bool:
        """True when bank rails are served by the simulated core banking system."""
        return self.CBS_MODE == _CBS_MODE_SIMULATED

    # ── Startup validation ────────────────────────────────────────────────────

    def validate(self) -> None:
        """
        Refuse to start with an unsafe or incoherent configuration.

        Called at import time so misconfiguration fails before the server binds
        a port, rather than at the first request that happens to need a secret.

        Most checks only apply outside DEBUG, where development defaults are
        expected. The core banking checks apply everywhere: an unrecognised
        `CBS_MODE` is a bug in any environment, and getting it wrong decides
        whether the platform moves simulated money or none at all.

        Raises:
            ConfigurationError: With every problem found, not just the first.
        """
        always: list[str] = []

        if self.CBS_MODE not in _CBS_MODES:
            always.append(
                f"CBS_MODE is '{self.CBS_MODE}'. Valid values are "
                f"{', '.join(sorted(_CBS_MODES))}."
            )
        elif self.CBS_MODE == _CBS_MODE_LIVE:
            always.append(
                "CBS_MODE=live requires bank adapters backed by a real core "
                "banking system, and none is integrated yet. Leave CBS_MODE "
                "unset until a bank agreement is in place; a rail that cannot "
                "reach a bank must fail loudly, not accept payments it will "
                "never settle."
            )

        if not 0.0 <= self.CBS_SETTLEMENT_FAILURE_RATE <= 1.0:
            always.append(
                f"CBS_SETTLEMENT_FAILURE_RATE must be between 0 and 1 "
                f"(got {self.CBS_SETTLEMENT_FAILURE_RATE})."
            )

        if self.CBS_SETTLEMENT_DELAY_SECONDS < 0:
            always.append("CBS_SETTLEMENT_DELAY_SECONDS cannot be negative.")

        if self.CBS_SETTLEMENT_POLL_INTERVAL_SECONDS <= 0:
            always.append("CBS_SETTLEMENT_POLL_INTERVAL_SECONDS must be positive.")

        if self.DEBUG:
            self._raise_if_any(always)
            return

        problems: list[str] = list(always)

        if self.SIMULATED_CBS and not self.ALLOW_SIMULATED_CBS:
            problems.append(
                "CBS_MODE=simulated outside DEBUG. Every balance and every "
                "transfer would be simulated, and nothing in the API says so "
                "to the person reading it. Set ALLOW_SIMULATED_CBS=true to "
                "state that this is a sandbox on purpose."
            )

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

        self._raise_if_any(problems)

    @staticmethod
    def _raise_if_any(problems: list[str]) -> None:
        """Abort startup listing every problem found, or return if there are none."""
        if not problems:
            return

        # ASCII only: this message is the last thing printed before the
        # process dies, and a Windows console (cp1252) mangles anything
        # else — exactly the failure mode that used to crash startup.
        raise ConfigurationError(
            "Refusing to start with an unsafe configuration:\n\n"
            + "\n\n".join(f"  - {p}" for p in problems)
            + "\n\nSee .env.example for the full variable list.\n"
        )


settings = Settings()
settings.validate()
