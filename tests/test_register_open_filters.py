"""Register Open button, checkbox filters, and must-have colours."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
COMMON = (ROOT / "app/static/js/common.js").read_text(encoding="utf-8")
CALC = (ROOT / "app/calculations.py").read_text(encoding="utf-8")


def test_open_button_is_not_blocked_by_actions_col():
    assert '<td class="actions-col">' in APP_JS
    assert '<td class="actions-col" onclick' not in APP_JS
    assert ".actions-col, a.btn" not in APP_JS
    assert 'closest("[data-action=\'open\']")' in APP_JS


def test_register_filters_are_checkboxes():
    assert 'id="filterPriority"' in INDEX
    assert 'id="filterProgram"' in INDEX
    assert 'id="filterStage"' in INDEX
    assert 'id="filterCouncil"' in INDEX
    assert 'id="filterList"' in INDEX
    assert "priorityFilter" not in INDEX
    assert "siteMatchesFilters" in APP_JS
    assert "selectedStages" in APP_JS
    assert 'id="btnFiltersAll"' in INDEX


def test_must_have_ok_is_yellow_not_green():
    assert 'if (band === "ok" || band === "warn") return "must-have warn"' in COMMON
    assert "moa_has_been_submitted" in CALC
    assert '"reason": "not_submitted"' in CALC
    assert '"reason": "past_due"' in CALC
