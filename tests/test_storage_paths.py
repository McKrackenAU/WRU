"""Admin-configurable file storage locations."""

from pathlib import Path

from app.storage_paths import (
    COST_ESTIMATES,
    DOCUMENTS,
    STORAGE_META,
    coerce_dir,
    default_dir,
)

ROOT = Path(__file__).resolve().parent.parent
ADMIN = (ROOT / "app/static/admin.html").read_text(encoding="utf-8")
NAV = (ROOT / "app/static/js/common.js").read_text(encoding="utf-8")
MAIN = (ROOT / "app/main.py").read_text(encoding="utf-8")
SETTINGS = (ROOT / "app/routers/settings_admin.py").read_text(encoding="utf-8")
STORAGE_JS = (ROOT / "app/static/js/storage.js").read_text(encoding="utf-8")
STORAGE_HTML = (ROOT / "app/static/storage.html").read_text(encoding="utf-8")
DOCS_PY = (ROOT / "app/routers/documents.py").read_text(encoding="utf-8")


def test_default_dirs_live_under_data():
    docs = default_dir(DOCUMENTS)
    costs = default_dir(COST_ESTIMATES)
    assert docs.name == "uploads"
    assert costs.name == "cost-estimates"
    assert "documents" in STORAGE_META
    assert "backups" in STORAGE_META


def test_blank_path_uses_default(tmp_path, monkeypatch):
    from app import storage_paths

    monkeypatch.setattr(storage_paths, "DATA_DIR", tmp_path)
    resolved = coerce_dir(DOCUMENTS, "")
    assert resolved == tmp_path / "uploads"
    assert resolved.is_dir()


def test_relative_path_resolves_under_data(tmp_path, monkeypatch):
    from app import storage_paths

    monkeypatch.setattr(storage_paths, "DATA_DIR", tmp_path)
    resolved = coerce_dir(DOCUMENTS, "hdd/docs")
    assert resolved == (tmp_path / "hdd/docs").resolve()
    assert resolved.is_dir()


def test_admin_storage_page_wired():
    assert 'href="/admin/storage"' in ADMIN
    assert 'href: "/admin/storage"' in NAV
    assert "admin_storage_page" in MAIN
    assert '@router.get("/storage")' in SETTINGS
    assert "put_storage_location" in SETTINGS
    assert "/api/admin/storage" in STORAGE_JS
    assert 'id="storageList"' in STORAGE_HTML
    assert "/api/admin/storage" in STORAGE_JS
    assert "documents_dir()" in DOCS_PY
