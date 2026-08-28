"""Startup must not die if an HDD path cannot be created."""

from pathlib import Path

from app.database import ensure_dir, env_path
from app.migrate import column_names, ensure_column

ROOT = Path(__file__).resolve().parents[1]


def test_ensure_dir_swallows_unwritable_path():
    path = Path("/dev/null/wru-cannot-create")
    assert ensure_dir(path) == path


def test_env_path_does_not_mkdir(tmp_path, monkeypatch):
    missing = tmp_path / "not-created" / "data"
    monkeypatch.setenv("WRU_DATA_DIR", str(missing))
    parsed = env_path("WRU_DATA_DIR", tmp_path / "default")
    assert parsed == missing
    assert not missing.exists()
    assert not missing.parent.exists()


def test_import_does_not_mkdir_storage_paths():
    db = (ROOT / "app" / "database.py").read_text(encoding="utf-8")
    assert "DATA_DIR = env_path(" in db
    assert 'UPLOAD_DIR = DATA_DIR / "uploads"' in db
    assert 'ARCHIVE_DIR = UPLOAD_DIR / "archived"' in db
    assert "WRU_UPLOAD_DIR" not in db
    assert "WRU_ARCHIVE_DIR" not in db
    docs = (ROOT / "app" / "routers" / "documents.py").read_text(encoding="utf-8")
    maps = (ROOT / "app" / "routers" / "map_layers.py").read_text(encoding="utf-8")
    backup = (ROOT / "app" / "routers" / "backup.py").read_text(encoding="utf-8")
    tracker = (ROOT / "app" / "routers" / "import_tracker.py").read_text(encoding="utf-8")
    assert "STAGING_DIR = ensure_dir" not in docs
    assert "STAGING_DIR = ensure_dir" not in backup
    assert "STAGING_DIR = ensure_dir" not in tracker
    assert "KML_DIR = ensure_dir" not in maps


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


def test_update_script_refreshes_from_github_before_lock():
    text = (ROOT / "scripts" / "wru-update.sh").read_text(encoding="utf-8")
    self_at = text.find("WRU_UPDATE_SELF")
    flock_at = text.find("flock -n 9")
    stop_at = text.find("systemctl stop wru")
    assert self_at != -1 and flock_at != -1 and stop_at != -1
    assert self_at < flock_at < stop_at
    assert "sudo wru-update" in text
    assert "/usr/bin/wru-update" in text
    assert "/usr/bin/WRU-update" in text


def test_install_puts_sudo_wru_update_on_path():
    text = (ROOT / "install" / "wru-install.sh").read_text(encoding="utf-8")
    assert "install -m 755 \"$UPDATE_SRC\" /usr/bin/wru-update" in text
    assert "ln -sfn /usr/bin/wru-update /usr/bin/WRU-update" in text
    assert "NOPASSWD: /usr/bin/wru-update" in text
    assert "NOPASSWD: /usr/bin/WRU-update" in text


def test_install_does_not_abort_on_hdd_or_optional_jpeg():
    text = (ROOT / "install" / "wru-install.sh").read_text(encoding="utf-8")
    assert "WRU_UPLOAD_DIR" not in text
    assert "WRU_ARCHIVE_DIR" not in text
    assert "libjpeg62-turbo ||" in text
    assert 'mv "$NEW_APP" "$APP_DIR"' in text
    assert 'python3 -m venv "$NEW_APP/.venv"' in text
    # Must pip into the new tree before replacing /opt/wru
    pip_at = text.find('pip install -r "$NEW_APP/requirements.txt"')
    swap_at = text.find('mv "$NEW_APP" "$APP_DIR"')
    wipe_old = text.find('rm -rf "$APP_DIR"')
    assert pip_at != -1 and swap_at != -1
    assert pip_at < swap_at
    assert wipe_old == -1 or wipe_old > swap_at


def test_engine_fails_fast_on_dead_postgres():
    text = (ROOT / "app" / "database.py").read_text(encoding="utf-8")
    assert "connect_timeout" in text
