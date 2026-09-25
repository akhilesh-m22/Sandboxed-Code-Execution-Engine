# tests/conftest.py
# Shared fixtures. Everything uses a throwaway DB in a temp directory so the
# test run never touches the real submissions.db.

from __future__ import annotations

import os
import pathlib
import tempfile

import pytest


@pytest.fixture()
def tmp_db_path(tmp_path: pathlib.Path) -> pathlib.Path:
    """Point config.DB_PATH at a per-test temp SQLite file (isolated)."""
    db = tmp_path / "test_submissions.db"
    os.environ["DB_PATH"] = str(db)
    yield db
    os.environ.pop("DB_PATH", None)