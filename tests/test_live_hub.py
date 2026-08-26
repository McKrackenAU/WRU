"""Live multi-user refresh hub."""

from __future__ import annotations

import queue

from app.live_hub import LiveHub, bump_revision, current_revision, notify_sites_changed


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
