"""Activity message helpers."""

from types import SimpleNamespace

from app.activity import log_cost_added, log_stage_change, site_label
from app.models import WORKFLOW_LABELS


def test_site_label_includes_number():
    site = SimpleNamespace(road_name="Anderson Road", site_number="SN0715")
    assert site_label(site) == "Anderson Road - SN0715"


def test_stage_change_message_shape(monkeypatch):
    events = []

    class FakeDB:
        def add(self, obj):
            events.append(obj)

    site = SimpleNamespace(id=1, road_name="Anderson Road", site_number="SN0715")
    monkeypatch.setattr(
        "app.activity.stage_label_for",
        lambda db, key: WORKFLOW_LABELS.get(key, key or "Not started"),
    )
    log_stage_change(
        FakeDB(),
        site,
        before_key="moa_submitted",
        after_key="moa_received",
        who="Omar",
    )
    assert len(events) == 1
    assert events[0].event_type == "status"
    assert events[0].message == "Omar edited Anderson Road - SN0715: MoA Submitted → MoA Received"


def test_cost_added_message_shape():
    events = []

    class FakeDB:
        def add(self, obj):
            events.append(obj)

    site = SimpleNamespace(id=2, road_name="Dynon Rd", site_number="D1")
    log_cost_added(FakeDB(), site, kind="traffic", who="Omar")
    assert events[0].message == "Omar edited Dynon Rd - D1, added traffic costs"
