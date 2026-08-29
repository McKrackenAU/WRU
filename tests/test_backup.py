"""WRU server backup zip packing and restore helpers."""

import json
from pathlib import Path
from zipfile import ZipFile

from app.backup import (
    BACKUP_FORMAT,
    DUMP_NAME,
    MANIFEST_NAME,
    build_manifest,
    dump_database,
    read_manifest,
    restore_uploads,
    unique_zip_path,
    write_backup_zip,
)


def test_unique_zip_path_dedupes():
    used: set[str] = set()
    assert unique_zip_path(used, "DYNON/Plan/a.pdf") == "DYNON/Plan/a.pdf"
    assert unique_zip_path(used, "DYNON/Plan/a.pdf") == "DYNON/Plan/a (2).pdf"
    assert unique_zip_path(used, "DYNON/Plan/a.pdf") == "DYNON/Plan/a (3).pdf"


def test_manifest_format():
    man = build_manifest()
    assert man["format"] == BACKUP_FORMAT
    assert man["database"]["file"] == DUMP_NAME


def test_write_backup_zip_roundtrip(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    sample = uploads / "site1_hello.txt"
    sample.write_text("hello-wru", encoding="utf-8")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "nearmap_api_key").write_text("nm-test-key", encoding="utf-8")

    def fake_dump(dest: Path) -> None:
        dest.write_bytes(b"PGDUMPFAKE" + b"\x00" * 64)

    monkeypatch.setattr("app.backup.documents_dir", lambda: uploads)
    monkeypatch.setattr("app.backup.DATA_DIR", data_dir)
    monkeypatch.setattr("app.backup.dump_database", fake_dump)

    zip_path = tmp_path / "backup.zip"
    man = write_backup_zip(zip_path)
    assert zip_path.is_file()
    assert man["format"] == BACKUP_FORMAT
    with ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert MANIFEST_NAME in names
        assert DUMP_NAME in names
        assert "uploads/site1_hello.txt" in names
        assert "config/nearmap_api_key" in names
        read = read_manifest(zf)
        assert read["format"] == BACKUP_FORMAT
        assert json.loads(zf.read(MANIFEST_NAME))["format"] == BACKUP_FORMAT


def test_restore_uploads_replaces(tmp_path, monkeypatch):
    live = tmp_path / "live-uploads"
    live.mkdir()
    (live / "old.bin").write_bytes(b"old")
    extracted = tmp_path / "extracted" / "uploads"
    extracted.mkdir(parents=True)
    nested = extracted / "cost-estimates"
    nested.mkdir()
    (nested / "new.bin").write_bytes(b"new")
    (extracted / ".keep").write_bytes(b"")
    monkeypatch.setattr("app.backup.documents_dir", lambda: live)
    restore_uploads(extracted)
    assert not (live / "old.bin").exists()
    assert (live / "cost-estimates" / "new.bin").read_bytes() == b"new"
    assert not (live / ".keep").exists()


def test_pg_dump_writes_custom_format(tmp_path):
    dest = tmp_path / "database.dump"
    dump_database(dest)
    assert dest.is_file()
    assert dest.stat().st_size > 64
    # Custom-format dumps start with PGDMP.
    assert dest.read_bytes()[:5] == b"PGDMP"


def test_backup_admin_page_wired():
    root = Path(__file__).resolve().parent.parent
    html = (root / "app/static/backup.html").read_text(encoding="utf-8")
    js = (root / "app/static/js/backup.js").read_text(encoding="utf-8")
    admin = (root / "app/static/admin.html").read_text(encoding="utf-8")
    nav = (root / "app/static/js/common.js").read_text(encoding="utf-8")
    main = (root / "app/main.py").read_text(encoding="utf-8")
    assert "Download backup" in html
    assert "Import backup" in html
    assert "/api/admin/backup/export" in js
    assert "/api/admin/backup/session" in js
    assert 'href="/admin/backup"' in admin
    assert 'href: "/admin/backup"' in nav
    assert 'admin_backup_page' in main
    assert "backup.router" in main
