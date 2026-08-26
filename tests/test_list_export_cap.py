"""Priority list export respects the lists page Show-top cap and filters."""

from pathlib import Path

from app.routers.export import ClientListView, apply_client_list_view

ROOT = Path(__file__).resolve().parent.parent
LISTS_JS = (ROOT / "app/static/js/lists.js").read_text(encoding="utf-8")
LISTS_HTML = (ROOT / "app/static/lists.html").read_text(encoding="utf-8")
EXPORT = (ROOT / "app/routers/export.py").read_text(encoding="utf-8")


def _row(road, *, pri=1, rank=1, program="Assets", start="2026-10-01", wait=3, moa="M1"):
    return {
        "priority": pri,
        "rank": rank,
        "road_name": road,
        "site_number": road[:1],
        "program": program,
        "indicative_start": start,
        "business_days_waiting": wait,
        "moa_number": moa,
    }


def test_limit_takes_the_first_n_after_sort():
    rows = [
        _row("C Road", start="2026-12-01", rank=3),
        _row("A Road", start="2026-10-01", rank=1),
        _row("B Road", start="2026-11-01", rank=2),
    ]
    out = apply_client_list_view(
        rows,
        ClientListView(limit=2, sort="start", direction="asc"),
    )
    assert [r["road_name"] for r in out] == ["A Road", "B Road"]


def test_limit_none_returns_all():
    rows = [_row("A"), _row("B"), _row("C")]
    out = apply_client_list_view(rows, ClientListView(limit=None))
    assert len(out) == 3


def test_empty_priority_filter_exports_nothing():
    rows = [_row("A", pri=1), _row("B", pri=2)]
    out = apply_client_list_view(rows, ClientListView(priorities=set(), limit=20))
    assert out == []


def test_program_and_priority_filters():
    rows = [
        _row("Keep", pri=1, program="Assets"),
        _row("Skip pri", pri=2, program="Assets"),
        _row("Skip prog", pri=1, program="Lifecycle"),
    ]
    out = apply_client_list_view(
        rows,
        ClientListView(priorities={"1"}, programs={"Assets"}),
    )
    assert [r["road_name"] for r in out] == ["Keep"]


def test_lists_page_wires_export_query_to_cap():
    assert "syncExportLinks" in LISTS_JS
    assert 'params.set("limit", String(state.cap))' in LISTS_JS
    assert "js-list-export" in LISTS_HTML
    assert 'data-export="/api/export/permits-list.pdf"' in LISTS_HTML
    assert 'data-export="/api/export/trims-list.pdf"' in LISTS_HTML
    assert "client_list_view" in EXPORT
    assert "apply_client_list_view" in EXPORT
    assert "limit: int | None = Query" in EXPORT
