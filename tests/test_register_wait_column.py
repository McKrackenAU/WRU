"""Register table shows Must-have and MoA Wait time as separate columns."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
STYLE_CSS = (ROOT / "app/static/css/style.css").read_text(encoding="utf-8")


def test_register_has_wait_time_column_header():
    assert 'sortHeader("must", "Must-have")' in APP_JS
    assert 'sortHeader("wait", "Wait time")' in APP_JS
    assert APP_JS.index('sortHeader("must", "Must-have")') < APP_JS.index(
        'sortHeader("wait", "Wait time")'
    )
    assert APP_JS.index('sortHeader("wait", "Wait time")') < APP_JS.index(
        'sortHeader("list", "List")'
    )


def test_register_rows_use_moa_wait_not_must_have_days():
    assert "moaWaitCell" in APP_JS
    assert "m.moa_wait" in APP_JS
    assert "business_days_waiting" in APP_JS
    assert 'colspan="10"' in APP_JS
    # Must-have cell is date/Received only — no inline · Nd suffix.
    assert " · ${escapeHtml(must.label)}" not in APP_JS


def test_wait_over_sla_style_exists():
    assert ".moa-wait.over-sla" in STYLE_CSS
