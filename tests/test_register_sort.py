"""Sites register column sort + lists cap/layout."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
LISTS_JS = (ROOT / "app/static/js/lists.js").read_text(encoding="utf-8")
LISTS_HTML = (ROOT / "app/static/lists.html").read_text(encoding="utf-8")
STYLE = (ROOT / "app/static/css/style.css").read_text(encoding="utf-8")


def test_register_column_headers_are_sortable():
    for key, label in (
        ("site", "Site"),
        ("status", "Status"),
        ("pri", "Pri"),
        ("start", "Start"),
        ("must", "Must-have"),
        ("wait", "Wait time"),
        ("list", "List"),
        ("moa", "MoA"),
    ):
        assert f'sortHeader("{key}", "{label}")' in APP_JS
    assert "setRegisterSort" in APP_JS
    assert "compareRegisterSites" in APP_JS
    assert "wru-register-sort" in APP_JS
    assert 'closest(".register-table [data-sort]")' in APP_JS


def test_lists_has_show_top_cap():
    assert 'id="listCap"' in LISTS_HTML
    assert "Show top" in LISTS_HTML
    assert "parseCap" in LISTS_JS
    assert "rows.slice(0, state.cap)" in LISTS_JS
    assert "wru-lists-cap" in LISTS_JS


def test_lists_filters_do_not_flex_grow_tall():
    assert "flex: 1 1 14rem" not in STYLE
    assert ".page-lists .lists-filters" in STYLE
    assert "flex-direction: row" in STYLE
    assert ".page-lists .lists-layout > .panel-card" in STYLE
    assert ".lists-cap-field" in STYLE
