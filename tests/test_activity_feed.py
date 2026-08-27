"""Activity feed page + API wiring."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = (ROOT / "app/main.py").read_text(encoding="utf-8")
COMMON = (ROOT / "app/static/js/common.js").read_text(encoding="utf-8")
TRACKING_HTML = (ROOT / "app/static/tracking.html").read_text(encoding="utf-8")
TRACKING_JS = (ROOT / "app/static/js/tracking.js").read_text(encoding="utf-8")
ACTIVITY_ROUTER = (ROOT / "app/routers/activity.py").read_text(encoding="utf-8")


def test_activity_router_mounted():
    assert "activity.router" in MAIN
    assert (ROOT / "app/routers/activity.py").is_file()
    assert 'prefix="/api/activity"' in ACTIVITY_ROUTER
    assert "mine: bool" in ACTIVITY_ROUTER


def test_nav_points_to_activity_feed():
    assert '{ href: "/tracking", label: "Activity", hint: "Who changed what" }' in COMMON


def test_tracking_page_is_activity_feed():
    assert "<h1>Activity</h1>" in TRACKING_HTML
    assert "Who changed what" in TRACKING_HTML
    assert 'id="typeFilter"' in TRACKING_HTML
    assert "/api/activity" in TRACKING_JS
    assert "event_type" in TRACKING_JS
    assert 'params.set("mine", "1")' in TRACKING_JS
    assert "My activity" in TRACKING_JS
    # Must not be the old program filter board
    assert "Program tracking" not in TRACKING_HTML
    assert "stageFilter" not in TRACKING_HTML
    assert "/api/sites?" not in TRACKING_JS
