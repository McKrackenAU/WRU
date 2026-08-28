"""Startup must not die if an HDD path cannot be created."""

from pathlib import Path

from app.database import ensure_dir
from app.migrate import column_names, ensure_column


def test_ensure_dir_swallows_unwritable_path():
    path = Path("/dev/null/wru-cannot-create")
    assert ensure_dir(path) == path


def test_ensure_column_skips_missing_table():
    # No documents_missing table — must not raise.
    ensure_column("wru_table_that_does_not_exist", "stored_bytes", "stored_bytes INTEGER")
    assert column_names("wru_table_that_does_not_exist") == set()
