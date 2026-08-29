"""Admin-configurable file storage locations."""

from pathlib import Path

from app.storage_paths import (
    COST_ESTIMATES,
    DOCUMENTS,
    KML,
    STORAGE_META,
    coerce_dir,
    default_dir,
    infer_mount,
    list_candidate_mounts,
    path_on_mount,
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


def test_path_on_mount_appends_kind_folders():
    assert path_on_mount(DOCUMENTS, "/mnt") == "/mnt/uploads"
    assert path_on_mount(KML, "/mnt") == "/mnt/uploads/kml"
    assert path_on_mount(COST_ESTIMATES, "/mnt/hdd") == "/mnt/hdd/uploads/cost-estimates"
    assert infer_mount(DOCUMENTS, "/mnt/uploads") == "/mnt"
    assert infer_mount(KML, "/mnt/uploads/kml") == "/mnt"
    assert infer_mount(DOCUMENTS, "/opt/wru-data/other") is None


def test_list_mounts_finds_child_disks(tmp_path, monkeypatch):
    from app import storage_paths

    disk = tmp_path / "disk1"
    disk.mkdir()
    data = tmp_path / "appdata"
    data.mkdir()
    monkeypatch.setattr(storage_paths, "MOUNT_ROOTS", (str(tmp_path),))
    monkeypatch.setattr(storage_paths, "DATA_DIR", data)
    paths = {item["path"] for item in list_candidate_mounts()}
    assert disk.resolve().as_posix() in paths
    assert data.resolve().as_posix() in paths


def test_admin_storage_page_wired():
    assert 'href="/admin/storage"' in ADMIN
    assert 'href: "/admin/storage"' in NAV
    assert "admin_storage_page" in MAIN
    assert '@router.get("/storage")' in SETTINGS
    assert "put_storage_location" in SETTINGS
    assert "/api/admin/storage" in STORAGE_JS
    assert 'id="storageList"' in STORAGE_HTML
    assert 'id="storageMounts"' in STORAGE_HTML
    assert 'id="btnApplyAll"' in STORAGE_HTML
    assert "apply_all" in STORAGE_JS
    assert "name=\"mount\"" in STORAGE_JS
    assert "describe_storage" in SETTINGS
    assert "documents_dir()" in DOCS_PY
