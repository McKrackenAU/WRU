"""Works map fills leftover viewport height instead of a 720px / 70vh cap."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = (ROOT / "app/static/css/style.css").read_text(encoding="utf-8")
MAP_HTML = (ROOT / "app/static/map.html").read_text(encoding="utf-8")
MAP_JS = (ROOT / "app/static/js/map.js").read_text(encoding="utf-8")


def test_map_page_uses_fill_height_layout():
    assert 'class="map-page"' in MAP_HTML
    assert "id=\"mapLayout\"" in MAP_HTML
    assert "id=\"mapCanvas\"" in MAP_HTML
    assert "height: min(70vh, 720px)" not in CSS
    assert "min-height: min(70vh, 720px)" not in CSS
    assert "body.map-page .shell-main" in CSS
    assert "body.map-page .main" in CSS
    assert "100dvh" in CSS
    assert "flex: 1 1 0" in CSS
    assert "grid-template-rows: minmax(0, 1fr)" in CSS
    assert "invalidateSize" in MAP_JS
