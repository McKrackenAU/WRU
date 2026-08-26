"""Static checks for live multi-user refresh wiring."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMMON = (ROOT / "app/static/js/common.js").read_text(encoding="utf-8")
APP = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
MAIN = (ROOT / "app/main.py").read_text(encoding="utf-8")
SITES = (ROOT / "app/routers/sites.py").read_text(encoding="utf-8")


def test_live_router_mounted():
    assert "live.router" in MAIN
    assert (ROOT / "app/routers/live.py").is_file()


def test_sites_notify_after_mutations():
    assert "notify_from_request" in SITES
    assert SITES.count("notify_from_request(") >= 6


def test_common_exposes_live_helpers():
    assert "export function liveClientId" in COMMON
    assert "export function onLiveSitesChanged" in COMMON
    assert "X-WRU-Client-Id" in COMMON
    assert "/api/live/events" in COMMON


def test_register_soft_refreshes_on_live_events():
    assert "onLiveSitesChanged(scheduleRemoteRefresh)" in APP
    assert "showRemoteBanner" in APP
    assert "live-remote-banner" in APP
