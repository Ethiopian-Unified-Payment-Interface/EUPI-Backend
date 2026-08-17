"""
Shared test configuration.

Environment must be set here rather than in individual test modules.
`backend.config.settings` reads `os.environ` once, at class-definition time, so
whichever test module happens to import `backend.config` first fixes the
database URL for the entire session. A module setting `DATABASE_URL` at its own
import time therefore only works when it happens to be imported first —
`test_e2e_superapp_p2p.py` passed alone and failed in the full suite for exactly
that reason, running against the repository's committed SQLite file and
inheriting users from previous runs.

conftest.py is imported before any test module, so this is the one place the
setting is guaranteed to take effect.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# A unique file per session: tests that exercise the real app singleton get a
# clean database every run instead of accumulating state across runs.
_SESSION_DB = Path(tempfile.gettempdir()) / f"eupi_tests_{uuid.uuid4().hex[:10]}.db"

os.environ["DATABASE_URL"] = f"sqlite:///{_SESSION_DB.as_posix()}"
# DEBUG relaxes the startup configuration check, which would otherwise refuse
# the development default secrets these tests rely on.
os.environ["DEBUG"] = "true"
os.environ.setdefault("ADMIN_BOOTSTRAP_EMAIL", "admin@kifiya.com")
os.environ.setdefault("ADMIN_BOOTSTRAP_PASSWORD", "E2ePass!123")


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    """Remove the session database once every test has finished."""
    import backend.main as main_module

    # Windows will not unlink a file with an open handle, so drop the pool first.
    if getattr(main_module, "_db", None) is not None:
        main_module._db.dispose()
    _SESSION_DB.unlink(missing_ok=True)
