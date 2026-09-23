"""Pinned Home graphs and accidental-remove-safe shortcuts."""

from pathlib import Path

from app.user_prefs import ALLOWED_CHART_METRICS, MAX_HOME_CHARTS, normalize_prefs

ROOT = Path(__file__).resolve().parent.parent
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
COMMON = (ROOT / "app/static/js/common.js").read_text(encoding="utf-8")
STYLE = (ROOT / "app/static/css/style.css").read_text(encoding="utf-8")
DASH_HTML = (ROOT / "app/static/dashboard.html").read_text(encoding="utf-8")
DASH_JS = (ROOT / "app/static/js/dashboard.js").read_text(encoding="utf-8")
ACCOUNT_HTML = (ROOT / "app/static/account.html").read_text(encoding="utf-8")
ACCOUNT_JS = (ROOT / "app/static/js/account.js").read_text(encoding="utf-8")
PREFS = (ROOT / "app/user_prefs.py").read_text(encoding="utf-8")


def test_version_is_217():
    assert VERSION == "2.18"


def test_quick_link_pills_have_no_remove_cross():
    assert "quick-link-remove" not in COMMON
    assert "quick-link-wrap" not in COMMON
    assert "quick-link-remove" not in STYLE
    assert 'class="quick-link"' in COMMON
    assert "Turn some off on Account" in COMMON
    assert "pills themselves have no" in ACCOUNT_HTML


def test_home_charts_default_and_normalize():
    empty = normalize_prefs(None)
    assert empty["home_charts"] == []
    cleaned = normalize_prefs(
        {
            "home_charts": [
                {"id": "c1", "title": "By stage", "metric": "stages", "chart": "pie"},
                {"id": "c1", "title": "dup", "metric": "bogus", "chart": "pie"},
                {"metric": "spend", "type": "bar"},
                {"title": "nope"},
            ]
        }
    )
    assert [c["metric"] for c in cleaned["home_charts"]] == ["stages", "spend"]
    assert cleaned["home_charts"][0]["chart"] == "pie"
    assert cleaned["home_charts"][1]["chart"] == "bar"
    assert cleaned["home_charts"][1]["id"] != cleaned["home_charts"][0]["id"]
    too_many = normalize_prefs(
        {"home_charts": [{"metric": "sites", "chart": "bar"} for _ in range(12)]}
    )
    assert len(too_many["home_charts"]) == MAX_HOME_CHARTS
    assert "stages" in ALLOWED_CHART_METRICS
    assert "spend" in ALLOWED_CHART_METRICS


def test_home_add_graph_ui():
    assert 'id="btnAddGraph"' in DASH_HTML
    assert 'id="homeCharts"' in DASH_HTML
    assert 'id="homeChartDialog"' in DASH_HTML
    assert 'id="chartMetric"' in DASH_HTML
    assert 'id="chartType"' in DASH_HTML
    assert "home_charts" in DASH_JS
    assert "seriesFor" in DASH_JS
    assert "pieSvg" in DASH_JS
    assert "saveUserPrefs" in DASH_JS
    assert "data-edit-chart" in DASH_JS
    assert "data-remove-chart" in DASH_JS
    assert ".home-charts" in STYLE
    assert ".pie-chart" in STYLE
    assert "home_charts" in ACCOUNT_JS
    assert "Add graph" in ACCOUNT_HTML
    assert "ALLOWED_CHART_METRICS" in PREFS
