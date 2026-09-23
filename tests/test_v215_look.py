"""Per-user look, top-bar shortcuts, and weather radar."""

from pathlib import Path

from app.user_prefs import normalize_prefs

ROOT = Path(__file__).resolve().parent.parent
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
COMMON = (ROOT / "app/static/js/common.js").read_text(encoding="utf-8")
STYLE = (ROOT / "app/static/css/style.css").read_text(encoding="utf-8")
ACCOUNT_HTML = (ROOT / "app/static/account.html").read_text(encoding="utf-8")
ACCOUNT_JS = (ROOT / "app/static/js/account.js").read_text(encoding="utf-8")
AUTH = (ROOT / "app/routers/auth.py").read_text(encoding="utf-8")
INDEX = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
LOGIN_JS = (ROOT / "app/static/js/login.js").read_text(encoding="utf-8")


def test_version_is_215():
    assert VERSION == "2.21"


def test_prefs_keep_separate_light_and_dark_palettes():
    empty = normalize_prefs(None)
    assert empty["colors_light"]["accent"] == ""
    assert empty["colors_dark"]["accent"] == ""
    legacy = normalize_prefs({"colors": {"accent": "#112233", "bg": "#abcdef"}})
    assert legacy["colors_light"]["accent"] == "#112233"
    assert legacy["colors_dark"]["bg"] == "#abcdef"
    split = normalize_prefs(
        {
            "theme": "dark",
            "colors_light": {"accent": "#004825"},
            "colors_dark": {"accent": "#3dd68c", "bg": "#111111"},
        }
    )
    assert split["theme"] == "dark"
    assert split["colors_light"]["accent"] == "#004825"
    assert split["colors_dark"]["bg"] == "#111111"
    assert split["colors_light"]["bg"] == ""


def test_empty_quick_links_stay_empty():
    assert normalize_prefs({"quick_links": []})["quick_links"] == []
    assert normalize_prefs({"quick_links": ["/costs", "/bogus"]})["quick_links"] == ["/costs"]


def test_topbar_plus_and_radar_wiring():
    assert "quick-link-add" in COMMON
    assert "initQuickLinks" in COMMON
    assert "openWeatherRadar" in COMMON
    assert "embed.windy.com" in COMMON
    assert "rainviewer.com" in COMMON
    assert "paletteForTheme" in COMMON
    assert "colors_light" in COMMON
    assert "THEME_KEY}:${who}" in COMMON or "${THEME_KEY}:" in COMMON
    assert "wru_username" in COMMON
    assert "wru_username" in LOGIN_JS
    assert "colors_light" in AUTH
    assert "colors_dark" in AUTH


def test_account_has_two_palettes():
    assert 'id="colorLightAccent"' in ACCOUNT_HTML
    assert 'id="colorDarkAccent"' in ACCOUNT_HTML
    assert "collectedPalette" in ACCOUNT_JS
    assert "colors_dark" in ACCOUNT_JS
    assert "quick-link-add" in STYLE
    assert "weather-radar-dialog" in STYLE
    assert "wru-tgs-theme:" in INDEX
    assert "wru_username" in INDEX
