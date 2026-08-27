"""Dark-theme fluoro accents, program header polish, and brighter export greens."""

from pathlib import Path

from app.pdf_brand import GREEN, GREEN_HEX, GREEN_MID, GREEN_MID_HEX

ROOT = Path(__file__).resolve().parent.parent
STYLE = (ROOT / "app/static/css/style.css").read_text(encoding="utf-8")
EXPORT_PY = (ROOT / "app/routers/export.py").read_text(encoding="utf-8")
COST_XLSX = (ROOT / "app/cost_export.py").read_text(encoding="utf-8")
SPEND_XLSX = (ROOT / "app/spend_export.py").read_text(encoding="utf-8")


def test_user_menu_button_is_fluoro_green():
    assert ".user-menu-btn" in STYLE
    assert "background: var(--ventia-green)" in STYLE
    btn = STYLE.split(".user-menu-btn {", 1)[1].split("}", 1)[0]
    assert "var(--ventia-green)" in btn
    assert "border: 1px solid var(--ventia-border)" not in btn
    assert "html.dark" in STYLE
    assert "--ventia-green: #3dd68c" in STYLE


def test_program_title_has_no_floating_left_rule():
    title = STYLE.split(".register-program-title {", 1)[1].split("}", 1)[0]
    assert "border-left" not in title
    name = STYLE.split(".register-program-name {", 1)[1].split("}", 1)[0]
    assert "color: var(--ventia-green)" in name
    head = STYLE.split(".register-program-head {", 1)[1].split("}", 1)[0]
    assert "inset 3px 0 0 var(--ventia-green)" in head


def test_export_greens_are_brighter_than_forest():
    assert GREEN_HEX == "0B7A45"
    assert GREEN_MID_HEX == "00C45A"
    assert str(GREEN).lower() != "#004825"
    assert str(GREEN_MID).lower() != "#00994d"
    assert "GREEN_HEX" in EXPORT_PY
    assert "GREEN_HEX" in COST_XLSX
    assert "GREEN_HEX" in SPEND_XLSX
    assert "0B3D2E" not in EXPORT_PY
    assert "0B3D2E" not in COST_XLSX
