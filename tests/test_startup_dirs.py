"""Startup must not die if an HDD path cannot be created."""

from pathlib import Path

from app.database import ensure_dir
from app.migrate import column_names, ensure_column

ROOT = Path(__file__).resolve().parents[1]


def test_ensure_dir_swallows_unwritable_path():
    path = Path("/dev/null/wru-cannot-create")
    assert ensure_dir(path) == path


def test_ensure_column_skips_missing_table():
    # No documents_missing table — must not raise.
    ensure_column("wru_table_that_does_not_exist", "stored_bytes", "stored_bytes INTEGER")
    assert column_names("wru_table_that_does_not_exist") == set()


def test_requirements_do_not_hard_require_pillow():
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "pillow==" not in text.lower()


def test_update_script_traps_before_stopping_wru():
    text = (ROOT / "scripts" / "wru-update.sh").read_text(encoding="utf-8")
    trap_at = text.find("trap restore_wru EXIT")
    stop_at = text.find("systemctl stop wru")
    assert trap_at != -1 and stop_at != -1
    assert trap_at < stop_at
