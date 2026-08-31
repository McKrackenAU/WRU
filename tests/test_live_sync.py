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
    assert "live_identity" in LIVE


def test_sites_notify_after_mutations():
    assert "notify_from_request" in SITES
    assert SITES.count("notify_from_request(") >= 6


def test_sse_does_not_block_a_thread_per_client():
    assert "to_thread" not in LIVE
    assert "get_nowait" in LIVE
    assert "cached_live_identity" in LIVE


def test_common_has_revision_poll_and_coalesced_refresh():
    assert "syncLiveRevision" in COMMON
    assert "markLiveRevision" in COMMON
    assert "/api/live/revision" in COMMON
    assert "flushLiveRefresh" in COMMON
    assert "checkLiveRevision" in COMMON
    assert "boot_id" in COMMON
    assert "asset_version" in COMMON
    assert "hardReloadForUpdate" in COMMON
    assert "applyAppUpdate" in COMMON
    assert "pendingAppUpdate" in COMMON
    assert 'ident === "reload"' not in COMMON
    assert "wru:app-update" in COMMON
    assert "ingestLiveHeaders" in COMMON
    assert "X-WRU-Revision" in COMMON
    assert "X-WRU-Boot-Id" in COMMON
    assert "X-WRU-Asset-Version" in COMMON
    assert "bootstrapLiveSync" in COMMON
    assert "LIVE_POLL_SSE_MS" in COMMON
    assert "pendingBootHits" in COMMON
    assert "conn_id" not in COMMON  # client uses client_id only


def test_chrome_starts_live_sync_on_every_page():
    assert "bootstrapLiveSync()" in COMMON
    idx_inject = COMMON.rfind("export async function injectChrome")
    idx_boot = COMMON.rfind("bootstrapLiveSync()")
    assert idx_inject != -1 and idx_boot > idx_inject


def test_linked_generic_select_does_not_reuse_previous_site():
    assert "selected != null && selected !== \"\" ? String(selected) : sel.value" not in APP
    assert "arguments.length > 0" in APP
    assert "linked_generic_moa_id ?? \"\"" in APP or "linked_generic_moa_id ?? ''" in APP
    assert "fillGenericSelect(\"\")" in APP
    assert "state.suppressAutosave = true" in APP


def test_api_responses_stamp_live_identity():
    assert "class LiveIdentityMiddleware" in MAIN
    assert "X-WRU-Revision" in MAIN
    assert "X-WRU-Boot-Id" in MAIN
    assert "X-WRU-Asset-Version" in MAIN
    assert "cached_live_identity" in MAIN


def test_register_awaits_chrome_and_syncs_revision():
    assert "await injectChrome" in APP
    assert "await syncLiveRevision()" in APP
    assert "onLiveSitesChanged(applyRemoteRefresh)" not in APP
    assert "hydrateFromCache" in APP
    assert "wru-register-cache-v1" in APP
    assert "writeRegisterCache" in APP


def test_live_data_changes_flag_stale_instead_of_full_reload():
    ingest = COMMON[COMMON.find("function ingestLivePayload") :]
    ingest = ingest[: ingest.find("export function ensureLiveSync")]
    assert "markDataStale" in ingest
    assert "signalInboxIfForMe" in ingest
    assert "queueLiveRefresh" not in ingest
    assert "wru:data-stale" in COMMON
    assert "wru:notifications" in COMMON
    assert "liveStreamConnected" in COMMON
    assert "isRegisterStale" in COMMON


def test_inbox_publish_does_not_bump_revision():
    from app.live_hub import current_revision, hub, publish_inbox_event

    before = current_revision()
    conn_id, q = hub.subscribe("inbox-test", user_id=7, username="t")
    try:
        sent = publish_inbox_event([7, 8])
        ev = q.get(timeout=1)
        assert ev["type"] == "notification"
        assert ev["user_ids"] == [7, 8]
        assert sent >= 1
        assert current_revision() == before
    finally:
        hub.unsubscribe(conn_id)


def test_inbox_publish_skips_other_users():
    from queue import Empty

    from app.live_hub import hub, publish_inbox_event

    conn_a, qa = hub.subscribe("inbox-a", user_id=1, username="a")
    conn_b, qb = hub.subscribe("inbox-b", user_id=2, username="b")
    try:
        publish_inbox_event([1])
        ev = qa.get(timeout=1)
        assert ev["type"] == "notification"
        try:
            qb.get(timeout=0.05)
            raise AssertionError("other user should not receive inbox ping")
        except Empty:
            pass
    finally:
        hub.unsubscribe(conn_a)
        hub.unsubscribe(conn_b)
