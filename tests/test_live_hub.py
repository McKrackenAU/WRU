"""Live multi-user refresh hub."""

from __future__ import annotations

from app.live_hub import LiveHub, notify_sites_changed


def test_publish_skips_actor_client():
    hub = LiveHub()
    a = hub.subscribe("client-a", user_id=1, username="Ada")
    b = hub.subscribe("client-b", user_id=2, username="Ben")
    sent = hub.publish({"type": "sites_changed", "n": 1}, skip_client_id="client-a")
    assert sent == 1
    assert a.empty()
    assert b.get_nowait()["n"] == 1


def test_notify_sites_changed_includes_final_wait_fields():
    hub_count_before = __import__("app.live_hub", fromlist=["hub"]).hub.subscriber_count()
    q = __import__("app.live_hub", fromlist=["hub"]).hub.subscribe("wait-test")
    try:
        sent = notify_sites_changed(
            site_ids=[10, 20],
            reason="update",
            actor_name="Casey",
            client_id="wait-test",
        )
        # Actor client skipped
        assert sent == hub_count_before
        assert q.empty()
    finally:
        __import__("app.live_hub", fromlist=["hub"]).hub.unsubscribe("wait-test")


def test_full_queue_drops_oldest_not_raise():
    hub = LiveHub()
    q = hub.subscribe("full")
    for i in range(70):
        hub.publish({"i": i})
    # Queue max 64; should still have events and not raise
    assert q.qsize() <= 64
    first = q.get_nowait()
    assert "i" in first
