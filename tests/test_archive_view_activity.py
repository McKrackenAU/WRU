"""Archive open + activity feed wiring."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_JS = (ROOT / "app/static/js/archive.js").read_text(encoding="utf-8")
APP_JS = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
DASH_JS = (ROOT / "app/static/js/dashboard.js").read_text(encoding="utf-8")
SITES = (ROOT / "app/routers/sites.py").read_text(encoding="utf-8")


def test_archive_has_open_and_row_click():
    assert 'data-view="${s.id}"' in ARCHIVE_JS
    assert "data-view-row" in ARCHIVE_JS
    assert "/?view=" in ARCHIVE_JS


def test_register_opens_archived_view_readonly():
    assert "openArchivedOrActiveSite" in APP_JS
    assert "setDrawerReadOnly" in APP_JS
    assert "readOnlyArchive" in APP_JS
    assert 'params.get("view")' in APP_JS


def test_site_update_logs_stage_and_blocks_archived_edit():
    assert "log_stage_change" in SITES
    assert "This site is archived" in SITES


def test_dashboard_shows_activity_message():
    assert "e.message" in DASH_JS
    assert "No recent activity" in DASH_JS
