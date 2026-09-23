"""Wiring checks for the v2.14 operational update."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
INDEX = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
COMMON = (ROOT / "app/static/js/common.js").read_text(encoding="utf-8")
STYLE = (ROOT / "app/static/css/style.css").read_text(encoding="utf-8")
MAP_HTML = (ROOT / "app/static/map.html").read_text(encoding="utf-8")
MAP_JS = (ROOT / "app/static/js/map.js").read_text(encoding="utf-8")
COMMS_JS = (ROOT / "app/static/js/comms.js").read_text(encoding="utf-8")
DASH_HTML = (ROOT / "app/static/dashboard.html").read_text(encoding="utf-8")
DASH_JS = (ROOT / "app/static/js/dashboard.js").read_text(encoding="utf-8")
GANTT_HTML = (ROOT / "app/static/gantt.html").read_text(encoding="utf-8")
GANTT_JS = (ROOT / "app/static/js/gantt.js").read_text(encoding="utf-8")
ACCOUNT_HTML = (ROOT / "app/static/account.html").read_text(encoding="utf-8")
ACCOUNT_JS = (ROOT / "app/static/js/account.js").read_text(encoding="utf-8")
SHIFTS_HTML = (ROOT / "app/static/shifts.html").read_text(encoding="utf-8")
SHIFTS_JS = (ROOT / "app/static/js/shifts.js").read_text(encoding="utf-8")
COSTS_JS = (ROOT / "app/static/js/costs.js").read_text(encoding="utf-8")
DOCS_JS = (ROOT / "app/static/js/documents.js").read_text(encoding="utf-8")
MAIN = (ROOT / "app/main.py").read_text(encoding="utf-8")
AUTH = (ROOT / "app/routers/auth.py").read_text(encoding="utf-8")
PREFS = (ROOT / "app/user_prefs.py").read_text(encoding="utf-8")


def test_version_is_214():
    assert VERSION == "2.21"


def test_filter_checkboxes_and_cost_filter():
    assert "width: 16px" in STYLE
    assert 'html.dark .lists-check input[type="checkbox"]' in STYLE
    assert 'id="filterCost"' in INDEX
    assert "selectedCosts" in APP_JS
    assert "has_traffic_cost" in APP_JS
    assert "fillPavingSelect" in APP_JS
    assert 'id="fPaving"' in INDEX


def test_document_chooser_and_export_selection():
    assert "openDocumentChooser" in COMMON
    assert "openDocumentChooser" in APP_JS
    assert "openDocumentChooser" in DOCS_JS
    assert 'id="exportDialog"' in INDEX
    assert "export/selection.csv" in APP_JS
    assert "btnExportSelected" in INDEX


def test_map_attach_and_gpkg():
    assert 'id="drawAttachMode"' in MAP_HTML
    assert 'id="gpkgFile"' in MAP_HTML
    assert "uploadGpkg" in MAP_JS
    assert "/api/map/gpkg" in MAP_JS
    assert "drawAttachMode" in MAP_JS


def test_comms_toggles_and_date_sort():
    assert "sheet-toggle" in COMMS_JS
    assert "comms_sort" in COMMS_JS
    assert "combinedVisibleRows" in COMMS_JS
    assert "data-comms-sort" in COMMS_JS


def test_home_costs_and_account_prefs():
    assert 'id="homeGrid"' in DASH_HTML
    assert "cost_totals" in DASH_JS
    assert "spend_totals" in DASH_JS
    assert "home_widgets" in DASH_JS
    assert 'id="accountTheme"' in ACCOUNT_HTML
    assert 'id="colorLightAccent"' in ACCOUNT_HTML
    assert "quick_links" in ACCOUNT_JS
    assert "home_widgets" in ACCOUNT_JS
    assert "saveUserPrefs" in COMMON
    assert "colors_light" in ACCOUNT_JS


def test_shifts_weather_and_gantt_msp():
    assert '"/shifts"' in MAIN
    assert "Shift reports" in SHIFTS_HTML
    assert "fetchLiveWeather" in SHIFTS_JS
    assert "include_archived" in SHIFTS_JS
    assert 'id="btnImportMsp"' in GANTT_HTML
    assert "import-msp" in GANTT_JS
    assert "undo-import" in GANTT_JS
    assert "exportSubcontractor" in GANTT_JS


def test_prefs_merge_and_season_export():
    assert "merged" in AUTH
    assert "normalize_prefs" in AUTH
    assert "DEFAULT_HOME_WIDGETS" in PREFS
    assert "exportSeasonPdf" in COSTS_JS
    assert "/api/costs/season.pdf" in COSTS_JS
    assert "combinedCostHint" in COSTS_JS or "combined/" in COSTS_JS
