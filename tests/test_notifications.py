"""Tag-based notification rules and header bell wiring."""

from pathlib import Path
from types import SimpleNamespace

from app.notify import (
    normalize_tags,
    planned_notifications,
    render_body,
    rule_matches_event,
    user_matches_rule,
)

ROOT = Path(__file__).resolve().parent.parent
MAIN = (ROOT / "app/main.py").read_text(encoding="utf-8")
COMMON = (ROOT / "app/static/js/common.js").read_text(encoding="utf-8")
USERS_HTML = (ROOT / "app/static/users.html").read_text(encoding="utf-8")
USERS_JS = (ROOT / "app/static/js/users.js").read_text(encoding="utf-8")
ADMIN = (ROOT / "app/static/admin.html").read_text(encoding="utf-8")
NOTIFY_JS = (ROOT / "app/static/js/notifications.js").read_text(encoding="utf-8")
NOTIFY_ADMIN = (ROOT / "app/static/js/notify_admin.js").read_text(encoding="utf-8")
NOTIFY_HTML = (ROOT / "app/static/notifications.html").read_text(encoding="utf-8")
SITES = (ROOT / "app/routers/sites.py").read_text(encoding="utf-8")
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def test_version_is_208():
    assert VERSION == "2.08"


def test_normalize_tags_dedupes_and_caps():
    assert normalize_tags("Structures, structures,  ") == ["structures"]
    assert normalize_tags(["Omar Crew", "structures"]) == ["omar-crew", "structures"]
    assert normalize_tags("") == []
    long = ["t" + str(i) for i in range(20)]
    assert len(normalize_tags(long)) == 12


def test_user_matches_rule_by_tag_or_id():
    omar = SimpleNamespace(id=7, tags=["structures"], username="omar")
    other = SimpleNamespace(id=8, tags=["asphalt"], username="lee")
    rule = SimpleNamespace(target_tags=["structures"], target_user_ids=[])
    assert user_matches_rule(omar, rule)
    assert not user_matches_rule(other, rule)
    named = SimpleNamespace(target_tags=[], target_user_ids=[8])
    assert user_matches_rule(other, named)
    assert not user_matches_rule(omar, named)


def test_rule_matches_structures_ready_for_works():
    rule = SimpleNamespace(
        enabled=True,
        trigger="stage_entered",
        stage_key="ready_for_works",
        program="Structures",
    )
    site = SimpleNamespace(program="Structures", road_name="Anderson Road", site_number="S1")
    assert rule_matches_event(rule, site, "moa_received", "ready_for_works")
    assert not rule_matches_event(rule, site, "ready_for_works", "ready_for_works")
    pavement = SimpleNamespace(program="Pavements")
    assert not rule_matches_event(rule, pavement, "moa_received", "ready_for_works")
    disabled = SimpleNamespace(
        enabled=False,
        trigger="stage_entered",
        stage_key="ready_for_works",
        program="Structures",
    )
    assert not rule_matches_event(disabled, site, "moa_received", "ready_for_works")


def test_planned_notifications_fans_out_to_tagged_users():
    rule = SimpleNamespace(
        id=1,
        enabled=True,
        trigger="stage_entered",
        stage_key="ready_for_works",
        program="Structures",
        target_tags=["structures"],
        target_user_ids=[],
    )
    omar = SimpleNamespace(id=3, username="omar", active=True, tags=["structures"])
    lee = SimpleNamespace(id=4, username="lee", active=True, tags=["asphalt"])
    root = SimpleNamespace(id=1, username="root", active=True, tags=["structures"])
    site = SimpleNamespace(id=10, program="Structures", road_name="Bridge Rd", site_number="B1")
    pairs = planned_notifications([rule], [omar, lee, root], site, "moa_received", "ready_for_works")
    assert [u.username for u, _ in pairs] == ["omar"]
    assert planned_notifications([rule], [omar], site, "ready_for_works", "ready_for_works") == []


def test_render_body_default_and_template():
    site = SimpleNamespace(road_name="Bridge Rd", site_number="B1", program="Structures")
    assert "Ready for Works" in render_body("", site, "ready_for_works", "Ready for Works")
    assert render_body("{program} · {site}", site, "ready_for_works", "Ready for Works") == (
        "Structures · Bridge Rd - B1"
    )


def test_site_update_ignores_unknown_client_fields():
    from app.schemas import SiteUpdate

    payload = SiteUpdate.model_validate({"road_name": "Bridge Rd", "legacy_client_flag": True})
    assert payload.road_name == "Bridge Rd"
    assert not hasattr(payload, "legacy_client_flag")


def test_bell_and_admin_wired():
    assert "notifyBellBtn" in COMMON
    assert 'href: "/admin/notifications"' in COMMON
    assert "mountNotifications" in COMMON
    assert "/api/notifications" in NOTIFY_JS
    assert "dispatch_stage_notifications" in SITES
    assert 'id="newTagsPicker"' in USERS_HTML
    assert "data-tags" in USERS_JS
    assert 'href: "/admin/tags"' in COMMON
    assert 'href="/admin/notifications"' in ADMIN
    assert "admin_notifications_page" in MAIN
    assert 'id="createRuleForm"' in NOTIFY_HTML
    assert "/api/admin/notification-rules" in NOTIFY_ADMIN
    assert "wru:sites-changed" in COMMON
    assert "wru:app-update" in COMMON
    assert "pendingAppUpdate" in COMMON
    assert "applyAppUpdate" in COMMON
    assert "notifyApplyUpdate" in NOTIFY_JS
    assert "liveStreamConnected" in NOTIFY_JS
    assert "POLL_MS = 120000" in NOTIFY_JS
    assert "X-WRU-Client-Version" in COMMON
    assert 'ident === "reload"' not in COMMON
