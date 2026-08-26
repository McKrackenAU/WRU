"""Site drawer layout and manual priority override."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
STYLE = (ROOT / "app/static/css/style.css").read_text(encoding="utf-8")
CALC = (ROOT / "app/calculations.py").read_text(encoding="utf-8")
MODELS = (ROOT / "app/models.py").read_text(encoding="utf-8")


def test_drawer_has_grouped_sections():
    assert 'class="form-section"' in INDEX
    assert "<h3>Schedule &amp; priority</h3>" in INDEX
    assert 'id="fPriority"' in INDEX
    assert "Auto (from must-have)" in INDEX
    assert 'class="check-row' in INDEX


def test_drawer_collects_priority_manual():
    assert "priority_manual:" in APP_JS
    assert 'id="fPriority"' in APP_JS or "$(\"fPriority\")" in APP_JS
    assert "if manual in (1, 2):" in CALC
    assert "priority_manual" in MODELS


def test_drawer_layout_css():
    assert "min(46rem, 100vw)" in STYLE
    assert ".form-section" in STYLE
    assert ".check-row" in STYLE
    assert ".priority.is-manual" in STYLE
