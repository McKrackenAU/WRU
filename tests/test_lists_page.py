"""Client priority lists: open, filters, sorting."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LISTS_HTML = (ROOT / "app/static/lists.html").read_text(encoding="utf-8")
LISTS_JS = (ROOT / "app/static/js/lists.js").read_text(encoding="utf-8")


def test_lists_page_has_open_and_start_columns():
    assert LISTS_HTML.count("data-sort=\"start\"") == 2
    assert 'href="/?highlight=${s.id}"' in LISTS_JS or 'href="/?highlight=' in LISTS_JS
    assert "Open" in LISTS_JS
    assert "colspan=\"8\"" in LISTS_JS


def test_lists_checkbox_filters_and_sort():
    assert 'id="filterPriority"' in LISTS_HTML
    assert 'id="filterProgram"' in LISTS_HTML
    assert "selectedPriorities" in LISTS_JS
    assert "selectedPrograms" in LISTS_JS
    assert 'sortKey: "start"' in LISTS_JS
    assert "th-sort" in LISTS_HTML
