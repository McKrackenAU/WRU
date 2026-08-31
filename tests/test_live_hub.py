"""Live multi-user refresh hub."""

from __future__ import annotations

import queue

from app.live_hub import LiveHub, bump_revision, current_revision, live_identity, notify_sites_changed


def test_subscribe_uses_unique_connection_ids():
    hub = LiveHub()
    conn_a, q_a = hub.subscribe("browser-1", user_id=1)
    conn_b, q_b = hub.subscribe("browser-1", user_id=1)
    assert conn_a != conn_b
    sent = hub.publish({"type": "sites_changed", "n": 1})
    assert sent == 2
    assert q_a.get_nowait()["n"] == 1
    assert q_b.get_nowait()["n"] == 1
    hub.unsubscribe(conn_a)
    assert hub.subscriber_count() == 1
    hub.unsubscribe(conn_b)
    assert hub.subscriber_count() == 0


def test_unsubscribe_old_connection_does_not_remove_new_one():
    hub = LiveHub()
    conn_old, q_old = hub.subscribe("tab-1")
    conn_new, q_new = hub.subscribe("tab-1")
    hub.unsubscribe(conn_old)
    assert hub.subscriber_count() == 1
    hub.publish({"ok": True})
    assert q_new.get_nowait()["ok"] is True
    assert q_old.empty()
    hub.unsubscribe(conn_new)


def test_publish_skips_actor_client_not_connection():
    hub = LiveHub()
    conn_a, q_a = hub.subscribe("client-a")
    conn_b, q_b = hub.subscribe("client-b")
    sent = hub.publish({"type": "sites_changed", "n": 1}, skip_client_id="client-a")
    assert sent == 1
    assert q_a.empty()
    assert q_b.get_nowait()["n"] == 1
    hub.unsubscribe(conn_a)
    hub.unsubscribe(conn_b)


def test_revision_increments_on_notify():
    before = current_revision()
    notify_sites_changed(site_ids=[1], reason="update", client_id="local")
    after = current_revision()
    assert after == before + 1


def test_live_identity_includes_boot_and_version():
    ident = live_identity()
    assert ident["revision"] == current_revision()
    assert ident["boot_id"]
    assert ident["asset_version"]
    assert "subscribers" in ident


def test_revision_persists_across_disk_reread(tmp_path, monkeypatch):
    from app import live_hub

    path = tmp_path / "live_state.json"
    monkeypatch.setattr(live_hub, "STATE_PATH", path)
    live_hub._revision = 4
    live_hub._state_mtime_ns = 0
    live_hub._write_state_locked()
    live_hub._revision = 0
    live_hub._state_mtime_ns = 0
    assert current_revision() >= 4


def test_workers_reuse_disk_boot_id(tmp_path, monkeypatch):
    from app import live_hub

    path = tmp_path / "live_state.json"
    monkeypatch.setattr(live_hub, "STATE_PATH", path)
    live_hub._boot_id = ""
    live_hub._revision = 0
    live_hub._state_mtime_ns = 0
    live_hub._ident_cache = None
    live_hub._init_cluster_state()
    first = live_hub.boot_id()
    assert first
    live_hub._boot_id = "other-worker"
    live_hub._refresh_from_disk_locked()
    assert live_hub.boot_id() == first


def test_cached_live_identity_matches_live_identity():
    from app.live_hub import cached_live_identity, live_identity

    cached_a = cached_live_identity()
    cached_b = cached_live_identity()
    assert cached_a["boot_id"] == cached_b["boot_id"]
    ident = live_identity()
    assert ident["boot_id"] == cached_a["boot_id"]
    assert "revision" in cached_a


def test_full_queue_drops_oldest_not_raise():
    hub = LiveHub()
    _, q = hub.subscribe("full")
    for i in range(70):
        hub.publish({"i": i})
    assert q.qsize() <= 64
    last = None
    while not q.empty():
        last = q.get_nowait()
    assert last is not None and "i" in last
