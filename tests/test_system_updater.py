"""System updater is a simple install screen; admin switch has the label inside."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "app/static/system.html").read_text(encoding="utf-8")
JS = (ROOT / "app/static/js/system.js").read_text(encoding="utf-8")
CSS = (ROOT / "app/static/css/style.css").read_text(encoding="utf-8")
COMMON = (ROOT / "app/static/js/common.js").read_text(encoding="utf-8")


def test_system_page_hides_advanced_and_logs():
    assert "Branch &amp; repository" not in HTML
    assert "first-time shell" not in HTML
    assert 'id="updBranch"' not in HTML
    assert 'id="shellHelp"' not in HTML
    assert 'id="btnToggleLog"' in HTML
    assert 'id="updProgress"' in HTML
    assert 'id="updLog"' in HTML
    assert "Pull &amp; install update" in HTML


def test_system_js_progress_and_log_toggle():
    assert "setProgress" in JS
    assert "setLogOpen" in JS
    assert "Hide logs" in JS
    assert "updBranch" not in JS
    assert "Need a first-time" not in JS
    assert "DEFAULT_BRANCH" in JS


def test_admin_switch_has_label_inside():
    assert 'class="admin-switch"' in COMMON
    assert 'admin-switch-label' in COMMON
    assert ">Admin</span>" in COMMON
    assert 'id="adminModeLabel"' not in COMMON
    assert ".admin-switch" in CSS
    assert ".admin-switch-label" in CSS
