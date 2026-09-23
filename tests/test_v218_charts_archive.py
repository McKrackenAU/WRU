"""Pie colours match numbers; chart filters; archive categories."""

from pathlib import Path

from app.lookups import ARCHIVE_KIND, LOOKUP_KINDS
from app.user_prefs import normalize_prefs

ROOT = Path(__file__).resolve().parent.parent
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
DASH_HTML = (ROOT / "app/static/dashboard.html").read_text(encoding="utf-8")
DASH_JS = (ROOT / "app/static/js/dashboard.js").read_text(encoding="utf-8")
INDEX = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
ARCHIVE_HTML = (ROOT / "app/static/archive.html").read_text(encoding="utf-8")
ARCHIVE_JS = (ROOT / "app/static/js/archive.js").read_text(encoding="utf-8")
SETTINGS_HTML = (ROOT / "app/static/settings.html").read_text(encoding="utf-8")
SETTINGS_JS = (ROOT / "app/static/js/settings.js").read_text(encoding="utf-8")
MODELS = (ROOT / "app/models.py").read_text(encoding="utf-8")
MIGRATE = (ROOT / "app/migrate.py").read_text(encoding="utf-8")
SITES = (ROOT / "app/routers/sites.py").read_text(encoding="utf-8")
DASH_PY = (ROOT / "app/routers/dashboard.py").read_text(encoding="utf-8")
LOOKUPS = (ROOT / "app/lookups.py").read_text(encoding="utf-8")
SCHEMAS = (ROOT / "app/schemas.py").read_text(encoding="utf-8")
MAIN = (ROOT / "app/main.py").read_text(encoding="utf-8")


def test_version_is_218():
    assert VERSION == "2.21"


def test_pie_uses_same_colors_for_slices_and_legend():
    assert "const usable = rows.filter" in DASH_JS
    assert "usable.forEach((item) =>" in DASH_JS
    assert "item.color" in DASH_JS
    assert "filteredJobs" in DASH_JS
    assert "hide_empty" in DASH_JS
    assert 'id="chartProgram"' in DASH_HTML
    assert 'id="chartCouncil"' in DASH_HTML
    assert 'id="chartIncludeArchived"' in DASH_HTML
    assert '"jobs": jobs' in DASH_PY


def test_chart_prefs_keep_program_filter():
    cleaned = normalize_prefs(
        {
            "home_charts": [
                {
                    "id": "c1",
                    "title": "Lifecycle stages",
                    "metric": "stages",
                    "chart": "pie",
                    "program": "Lifecycle pavements",
                    "council": "Melbourne",
                    "include_archived": True,
                    "hide_empty": False,
                }
            ]
        }
    )
    chart = cleaned["home_charts"][0]
    assert chart["program"] == "Lifecycle pavements"
    assert chart["council"] == "Melbourne"
    assert chart["include_archived"] is True
    assert chart["hide_empty"] is False
    defaulted = normalize_prefs({"home_charts": [{"metric": "stages", "chart": "bar"}]})
    assert defaulted["home_charts"][0]["hide_empty"] is True
    assert defaulted["home_charts"][0]["program"] == ""


def test_archive_category_wiring():
    assert ARCHIVE_KIND in LOOKUP_KINDS
    assert "archive_category" in MODELS
    assert "archive_category VARCHAR(128)" in MIGRATE
    assert "set_archive_category" in SITES
    assert "archive_category" in SCHEMAS
    assert "archive_categories" in MAIN
    assert 'id="archiveDialog"' in INDEX
    assert 'id="archiveCategory"' in INDEX
    assert "Add a new category" in INDEX
    assert "openArchiveDialog" in APP_JS
    assert 'id="categoryFilter"' in ARCHIVE_HTML
    assert "archive_category" in ARCHIVE_JS
    assert 'id="archiveLookupList"' in SETTINGS_HTML
    assert 'archive_category' in SETTINGS_JS
    assert "ARCHIVE_KIND" in LOOKUPS


def test_ensure_lookup_accepts_archive_kind():
    assert ARCHIVE_KIND == "archive_category"
    assert "archive_category" in LOOKUP_KINDS
