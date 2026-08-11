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


class Settings:
    # ── JWT ───────────────────────────────────────────────────────────────────
    JWT_SECRET_KEY: str = os.getenv(
        "JWT_SECRET_KEY",
        "kifiya-dev-secret-DO-NOT-USE-IN-PRODUCTION-change-me-now",
    )
    JWT_ALGORITHM: str = "HS256"
    JWT_TOKEN_TTL_SECONDS: int = int(os.getenv("JWT_TOKEN_TTL_SECONDS", "3600"))

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


settings = Settings()
