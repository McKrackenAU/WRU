"""Client priority lists: open, filters, sorting."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LISTS_HTML = (ROOT / "app/static/lists.html").read_text(encoding="utf-8")
LISTS_JS = (ROOT / "app/static/js/lists.js").read_text(encoding="utf-8")


def test_lists_page_has_open_and_start_columns():
    assert LISTS_HTML.count('data-sort="start"') == 2
    assert 'href="/?highlight=${s.id}"' in LISTS_JS or 'href="/?highlight=' in LISTS_JS
    assert "Open" in LISTS_JS
    assert 'colspan="8"' in LISTS_JS


def test_lists_checkbox_filters_and_sort():
    assert 'id="filterPriority"' in LISTS_HTML
    assert 'id="filterProgram"' in LISTS_HTML
    assert "selectedPriorities" in LISTS_JS
    assert "selectedPrograms" in LISTS_JS
    assert 'sortKey: "start"' in LISTS_JS
    assert "th-sort" in LISTS_HTML
    assert "setSort" in LISTS_JS
    # Unchecked / Clear must hide rows (empty set is not "show all")
    assert "Empty selection = show none" in LISTS_JS
    assert "if (!state.selectedPriorities.has(pri)) return false;" in LISTS_JS
    assert "if (!state.selectedPrograms.has(programKey(site))) return false;" in LISTS_JS
    # Document-level listeners survive filter re-renders; whole header cell is clickable
    assert 'document.addEventListener("change"' in LISTS_JS
    assert 'document.addEventListener("click"' in LISTS_JS
    assert 'closest(".lists-table thead th")' in LISTS_JS
    assert 'querySelector("[data-sort]")' in LISTS_JS
    # Header buttons must fill the cell so neighboring columns cannot steal clicks
    assert ".th-sort" in (ROOT / "app/static/css/style.css").read_text(encoding="utf-8")
    assert "min-width: 44rem" in (ROOT / "app/static/css/style.css").read_text(encoding="utf-8")
    # Export links follow the Show-top cap and current filters
    assert "syncExportLinks" in LISTS_JS
    assert "js-list-export" in LISTS_HTML
