"""Client priority lists page shows a compact six-column layout."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LISTS_HTML = (ROOT / "app/static/lists.html").read_text(encoding="utf-8")
LISTS_JS = (ROOT / "app/static/js/lists.js").read_text(encoding="utf-8")


def test_lists_page_has_only_requested_columns():
    expected = ["Pri", "Road", "Site #", "Program", "Council wait", "MoA #"]
    assert LISTS_HTML.count("<th>Pri</th>") == 2
    assert LISTS_HTML.count("<th>Road</th>") == 2
    assert LISTS_HTML.count("<th>Site #</th>") == 2
    assert LISTS_HTML.count("<th>Program</th>") == 2
    assert LISTS_HTML.count("<th>Council wait</th>") == 2
    assert LISTS_HTML.count("<th>MoA #</th>") == 2
    assert "<th>Stage</th>" not in LISTS_HTML
    for label in expected:
        assert f"<th>{label}</th>" in LISTS_HTML


def test_lists_rows_omit_stage_and_use_six_columns():
    assert "stageLabel" not in LISTS_JS
    assert "current_stage" not in LISTS_JS
    assert 'colspan="6"' in LISTS_JS
    assert "col-council" in LISTS_JS
    assert "col-moa" in LISTS_JS
