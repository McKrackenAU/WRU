"""Account page and self-service profile."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = (ROOT / "app/main.py").read_text(encoding="utf-8")
AUTH = (ROOT / "app/routers/auth.py").read_text(encoding="utf-8")
ACCOUNT_HTML = (ROOT / "app/static/account.html").read_text(encoding="utf-8")
ACCOUNT_JS = (ROOT / "app/static/js/account.js").read_text(encoding="utf-8")
COMMON = (ROOT / "app/static/js/common.js").read_text(encoding="utf-8")


def test_account_page_routed():
    assert '@app.get("/account")' in MAIN
    assert "account.html" in MAIN


def test_account_form_and_patch():
    assert 'id="accountDisplayName"' in ACCOUNT_HTML
    assert 'id="accountForm"' in ACCOUNT_HTML
    assert 'method: "PATCH"' in ACCOUNT_JS
    assert '"/api/auth/me"' in ACCOUNT_JS
    assert "def update_me" in AUTH


def test_user_menu_contains_account_and_activity():
    assert "userMenuBtn" in COMMON
    assert 'href="/tracking?mine=1"' in COMMON
    assert 'href="/account"' in COMMON
    assert "Dark mode" in COMMON
