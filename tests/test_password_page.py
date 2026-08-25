"""Password change page is available to signed-in users."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "app/static/password.html").read_text(encoding="utf-8")
JS = (ROOT / "app/static/js/password.js").read_text(encoding="utf-8")
COMMON = (ROOT / "app/static/js/common.js").read_text(encoding="utf-8")
LOGIN = (ROOT / "app/static/js/login.js").read_text(encoding="utf-8")


def test_password_page_has_required_fields():
    assert 'id="currentPassword"' in HTML
    assert 'id="newPassword"' in HTML
    assert 'id="confirmPassword"' in HTML
    assert 'id="passwordForm"' in HTML


def test_password_script_posts_change_endpoint():
    assert "/api/auth/change-password" in JS
    assert "must_change_password" in JS


def test_chrome_exposes_change_password():
    assert 'href="/password"' in COMMON
    assert "Change password" in COMMON


def test_login_sends_forced_change_to_password_page():
    assert "must_change_password" in LOGIN
    assert "/password" in LOGIN
