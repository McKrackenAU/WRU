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
    assert 'id="btnMarkStable"' in HTML
    assert 'id="btnMarkBeta"' in HTML
    assert "Mark as Stable" in HTML


def test_system_js_progress_and_log_toggle():
    assert "setProgress" in JS
    assert "setLogOpen" in JS
    assert "Hide logs" in JS
    assert "updBranch" not in JS
    assert "Need a first-time" not in JS
    assert "DEFAULT_BRANCH" in JS
    assert "/api/system/channel" in JS
    assert "channel_label" in JS
    assert "Currently on" in JS
    assert 's.branch || "main"' not in JS


def test_admin_switch_has_label_inside():
    assert 'class="admin-switch"' in COMMON
    assert "admin-switch-thumb" in COMMON
    assert "admin-switch-label" in COMMON
    assert ">Admin</span>" in COMMON
    assert ".admin-switch-thumb" in CSS
    assert 'id="adminModeLabel"' not in COMMON


def test_updater_copy_avoids_shell_setup():
    py = (ROOT / "app/routers/system.py").read_text(encoding="utf-8")
    probe = py.split("def _probe_can_update")[1].split("def _parse_github_slug")[0]
    assert "shell updater" not in probe.lower()
    assert "update from the shell" not in probe.lower()
    assert "shell command" not in probe.lower()
    assert "Ask whoever set up WRU" in probe
    assert "isn't installed" in probe
    assert "setStep(\"helper\", \"bad\")" in JS
    assert "helperMissing" in JS
    assert "left: calc(100% - var(--admin-switch-thumb)" in CSS
    assert ".version-chip.channel-beta" in CSS
    assert ".version-chip.channel-stable" in CSS
