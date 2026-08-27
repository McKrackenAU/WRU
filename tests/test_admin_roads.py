"""Admin settings page lets you edit roads so names pipe through the app."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_HTML = (ROOT / "app/static/settings.html").read_text(encoding="utf-8")
SETTINGS_JS = (ROOT / "app/static/js/settings.js").read_text(encoding="utf-8")
ADMIN = (ROOT / "app/routers/settings_admin.py").read_text(encoding="utf-8")
APP_JS = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")


def test_settings_has_editable_roads_list():
    assert "<h2>Roads</h2>" in SETTINGS_HTML
    assert 'id="roadLookupList"' in SETTINGS_HTML
    assert "Rename a road here to correct it everywhere" in SETTINGS_HTML
    assert "Rules, roads" in (ROOT / "app/static/admin.html").read_text(encoding="utf-8")
    assert "data-save-lookup" in SETTINGS_JS
    assert "saveLookupRow" in SETTINGS_JS
    assert "apply_lookup_update" in ADMIN
    assert "sites_updated" in ADMIN


def test_site_dropdown_uses_admin_roads_only():
    assert "fromSites" not in APP_JS.split("function knownRoads()", 1)[1].split("function collectedRoadName", 1)[0]
    assert "state.meta.roads" in APP_JS.split("function knownRoads()", 1)[1].split("function collectedRoadName", 1)[0]
