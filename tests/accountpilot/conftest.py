"""Shared fixtures for accountpilot tests."""

from __future__ import annotations

from collections.abc import (
    AsyncIterator,  # noqa: TC003 (used at runtime in fixture return type)
)
from pathlib import Path  # noqa: TC003 (used at runtime for path construction)

import aiosqlite  # noqa: TC002 (used at runtime in fixture return type)
import pytest

from accountpilot.core.db.connection import open_db


@pytest.fixture
def tmp_runtime(tmp_path: Path) -> Path:
    """Temporary `~/runtime/accountpilot/`-equivalent for a test."""
    runtime = tmp_path / "runtime"
    (runtime / "attachments").mkdir(parents=True)
    (runtime / "logs").mkdir()
    (runtime / "tmp").mkdir()
    (runtime / "secrets").mkdir(mode=0o700)
    return runtime


@pytest.fixture
def tmp_db_path(tmp_runtime: Path) -> Path:
    """Path to a fresh, empty SQLite DB file for the test."""
    return tmp_runtime / "accountpilot.db"


@pytest.fixture
async def tmp_db(tmp_db_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    """Async fixture: opened, migrated SQLite connection at tmp_db_path."""
    async with open_db(tmp_db_path) as db:
        yield db
