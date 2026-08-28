"""Open tabs soft-refresh when the installed app version changes."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMMON = (ROOT / "app/static/js/common.js").read_text(encoding="utf-8")
CSS = (ROOT / "app/static/css/style.css").read_text(encoding="utf-8")
LIVE = (ROOT / "app/routers/live.py").read_text(encoding="utf-8")
AUTH = (ROOT / "app/auth.py").read_text(encoding="utf-8")
LOGIN = (ROOT / "app/static/js/login.js").read_text(encoding="utf-8")
SYSTEM_HTML = (ROOT / "app/static/system.html").read_text(encoding="utf-8")
SW = (ROOT / "app/static/sw.js").read_text(encoding="utf-8")


def test_identity_compares_baked_html_version_not_first_payload():
    ident = COMMON.split("function rememberServerIdentity", 1)[1].split("function showUpdateBanner", 1)[0]
    assert "loadedAssetVersion()" in ident
    assert "incomingVersion !== prevVersion" in ident
    # Must not treat the first server payload as this tab's version.
    assert "pageAssetVersion == null && incomingVersion" not in ident


def test_soft_reload_shows_banner_then_reloads():
    assert "export function softReloadForUpdate" in COMMON
    assert "wru-update-banner" in COMMON
    assert "location.reload()" in COMMON
    assert "skip-waiting" in COMMON
    assert "wru-reloaded-for" in COMMON
    assert ".update-banner" in CSS


def test_login_and_chrome_watch_public_version():
    assert "/api/live/version" in COMMON
    assert "watchForAppUpdate" in COMMON
    assert "watchForAppUpdate" in LOGIN
    assert '"/api/live/version"' in AUTH or "/api/live/version" in AUTH
    assert 'def live_version' in LIVE


def test_system_page_mentions_open_tabs_refresh():
    assert "refresh on their own" in SYSTEM_HTML


def test_service_worker_still_network_only_for_api():
    assert 'startsWith("/api/")' in SW
    assert "skipWaiting" in SW
