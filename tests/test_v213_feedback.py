"""Wiring checks for the v2.13 feedback release."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
COMMON = (ROOT / "app/static/js/common.js").read_text(encoding="utf-8")
INDEX = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
DASH_HTML = (ROOT / "app/static/dashboard.html").read_text(encoding="utf-8")
DASH_JS = (ROOT / "app/static/js/dashboard.js").read_text(encoding="utf-8")
DASH_PY = (ROOT / "app/routers/dashboard.py").read_text(encoding="utf-8")
COMMS_JS = (ROOT / "app/static/js/comms.js").read_text(encoding="utf-8")
COMMS_PY = (ROOT / "app/routers/comms.py").read_text(encoding="utf-8")
NOTIFY = (ROOT / "app/notify.py").read_text(encoding="utf-8")
NOTIFY_ADMIN = (ROOT / "app/static/js/notify_admin.js").read_text(encoding="utf-8")
NOTIFY_HTML = (ROOT / "app/static/notifications.html").read_text(encoding="utf-8")
STAGES_JS = (ROOT / "app/static/js/stages.js").read_text(encoding="utf-8")
STAGES_PY = (ROOT / "app/routers/stages.py").read_text(encoding="utf-8")
BACKUP_JS = (ROOT / "app/static/js/backup.js").read_text(encoding="utf-8")
BACKUP_PY = (ROOT / "app/routers/backup.py").read_text(encoding="utf-8")
DOCS_PY = (ROOT / "app/routers/documents.py").read_text(encoding="utf-8")
DOCS_JS = (ROOT / "app/static/js/documents.js").read_text(encoding="utf-8")
SEED = (ROOT / "scripts/seed.py").read_text(encoding="utf-8")
INSTALL = (ROOT / "install/wru-install.sh").read_text(encoding="utf-8")
DOCKER = (ROOT / "Dockerfile").read_text(encoding="utf-8")
LOGIN_JS = (ROOT / "app/static/js/login.js").read_text(encoding="utf-8")
MAIN = (ROOT / "app/main.py").read_text(encoding="utf-8")
GENERICS_HTML = (ROOT / "app/static/generics.html").read_text(encoding="utf-8")
STYLE = (ROOT / "app/static/css/style.css").read_text(encoding="utf-8")


def test_version_is_213():
    assert VERSION == "2.13"


def test_login_lands_on_home_and_can_install():
    assert 'safeNextUrl(qs("next"), "/dashboard")' in LOGIN_JS
    assert 'id="btnInstallApp"' in (ROOT / "app/static/login.html").read_text(encoding="utf-8")


def test_home_is_tag_focused_landing():
    assert "<h1>Home</h1>" in DASH_HTML
    assert 'id="approvalList"' in DASH_HTML
    assert 'id="statusList"' in DASH_HTML
    assert 'id="commsPreview"' in DASH_HTML
    assert "recent_approvals" in DASH_JS
    assert "site_matches_user_focus" in DASH_PY
    assert "focus_tags" in DASH_PY
    assert 'href: "/dashboard"' in COMMON


def test_nav_and_page_names_are_grouped():
    assert 'group: "Today"' in COMMON
    assert 'href: "/generics"' in COMMON
    assert "side-nav-heading" in COMMON
    assert '"/generics"' in MAIN
    assert "Generic MoAs" in GENERICS_HTML
    assert "<title>Home · WRU</title>" in DASH_HTML
    assert "<title>Sites · WRU</title>" in INDEX
    assert "html.pwa-standalone .topbar" in STYLE


def test_register_hides_workflow_and_shows_extension():
    assert 'data-tab="workflow" hidden' in INDEX
    assert "badge-extension" in APP_JS
    assert "Extension applied" in APP_JS
    assert "badge-generic" in APP_JS
    assert 'href="/generics"' in INDEX


def test_combined_docs_auto_share():
    assert "combined_application_id" in DOCS_PY
    assert "share documents automatically" in INDEX
    assert 'id="docShareCombinedHint"' in INDEX


def test_comms_filters_roads_conflicts_and_overview_link():
    assert "ROAD_OTHER" in COMMS_JS
    assert "Other…" in COMMS_JS
    assert "dirtyFields" in COMMS_JS
    assert "expected_updated_at" in COMMS_JS
    assert "expected_updated_at" in COMMS_PY
    assert "Someone else changed" in COMMS_PY
    assert "skipDrawer" in COMMS_JS


def test_notification_flags_come_from_catalog():
    assert "TRIGGER_MOA_RECEIVED" in NOTIFY
    assert "TRIGGER_EXTENSION_APPLIED" in NOTIFY
    assert "ensure_builtin_notification_rules" in NOTIFY
    assert "trigger_catalog" in NOTIFY_ADMIN or "opts.triggers" in NOTIFY_ADMIN
    assert 'id="newTrigger"' in NOTIFY_HTML
    assert "dispatch_named_notifications" in (ROOT / "app/routers/sites.py").read_text(encoding="utf-8")


def test_programs_can_be_hard_removed():
    assert "hard=true" in STAGES_JS
    assert "hard: bool" in STAGES_PY


def test_backup_uses_chunked_session():
    assert "/api/admin/backup/export/session" in BACKUP_JS
    assert "downloadChunkedSession" in BACKUP_JS
    assert 'def export_backup_session' in BACKUP_PY or "/export/session" in BACKUP_PY


def test_pdf_viewer_and_generic_files_link():
    assert "openDocumentPreview" in COMMON
    assert "/api/documents/{id}/view" in DOCS_PY or '/view"' in DOCS_PY
    assert "moa_number" in DOCS_JS


def test_fresh_install_does_not_seed_sample_sites():
    assert "WRU_SKIP_SEED" in SEED
    assert "WRU_SEED_SAMPLE" in INSTALL
    assert "WRU_SEED_SAMPLE" in DOCKER
