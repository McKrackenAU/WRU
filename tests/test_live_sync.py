"""Static checks for live multi-user refresh wiring."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMMON = (ROOT / "app/static/js/common.js").read_text(encoding="utf-8")
APP = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
MAIN = (ROOT / "app/main.py").read_text(encoding="utf-8")
LIVE = (ROOT / "app/routers/live.py").read_text(encoding="utf-8")
SITES = (ROOT / "app/routers/sites.py").read_text(encoding="utf-8")


def test_live_router_mounted():
    assert "live.router" in MAIN
    assert (ROOT / "app/routers/live.py").is_file()


def test_live_revision_endpoint_exists():
    assert '"/revision"' in LIVE or "('/revision'" in LIVE
    assert "current_revision" in LIVE


def test_sites_notify_after_mutations():
    assert "notify_from_request" in SITES
    assert SITES.count("notify_from_request(") >= 6


def test_common_has_revision_poll_and_coalesced_refresh():
    assert "syncLiveRevision" in COMMON
    assert "markLiveRevision" in COMMON
    assert "/api/live/revision" in COMMON
    assert "flushLiveRefresh" in COMMON
    assert "checkLiveRevision" in COMMON
    assert "conn_id" not in COMMON  # client uses client_id only


def test_register_awaits_chrome_and_syncs_revision():
    assert "await injectChrome" in APP
    assert "await syncLiveRevision()" in APP
    assert "onLiveSitesChanged(applyRemoteRefresh)" in APP
