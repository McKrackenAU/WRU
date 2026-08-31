"""Tag library, category inheritance, and calendar notes."""

from pathlib import Path
from types import SimpleNamespace

from app.notify import (
    TRIGGER_CALENDAR_NOTE,
    calendar_note_link,
    calendar_note_recipients,
    category_tags_for_program,
    effective_job_tags,
    merge_tag_lists,
    normalize_tags,
    pretty_tag_label,
)

ROOT = Path(__file__).resolve().parent.parent
MAIN = (ROOT / "app/main.py").read_text(encoding="utf-8")
COMMON = (ROOT / "app/static/js/common.js").read_text(encoding="utf-8")
ADMIN = (ROOT / "app/static/admin.html").read_text(encoding="utf-8")
TAGS_HTML = (ROOT / "app/static/tags.html").read_text(encoding="utf-8")
TAGS_JS = (ROOT / "app/static/js/tags.js").read_text(encoding="utf-8")
STAGES_JS = (ROOT / "app/static/js/stages.js").read_text(encoding="utf-8")
STAGES_HTML = (ROOT / "app/static/stages.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
CAL_JS = (ROOT / "app/static/js/calendar.js").read_text(encoding="utf-8")
CAL_HTML = (ROOT / "app/static/calendar.html").read_text(encoding="utf-8")
NOTIFY = (ROOT / "app/notify.py").read_text(encoding="utf-8")
NOTIFY_ADMIN = (ROOT / "app/static/js/notify_admin.js").read_text(encoding="utf-8")
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def test_version_is_208():
    assert VERSION == "2.08"


def test_merge_and_effective_job_tags():
    assert merge_tag_lists(["structures"], "comms, structures") == ["structures", "comms"]
    site = SimpleNamespace(tags=["urgent", "structures"])
    assert effective_job_tags(site, ["structures", "comms"]) == ["structures", "comms", "urgent"]


def test_category_tags_match_program_name():
    structures = SimpleNamespace(name="Structures", tags=["structures"])
    pavements = SimpleNamespace(name="Pavements", tags=["asphalt"])
    db = SimpleNamespace(query=lambda _model: SimpleNamespace(all=lambda: [structures, pavements]))
    assert category_tags_for_program(db, "structures") == ["structures"]
    assert category_tags_for_program(db, "Pavements") == ["asphalt"]
    assert category_tags_for_program(db, "Unknown") == []
    assert category_tags_for_program(None, "Structures") == []


def test_calendar_note_link_and_recipients():
    assert calendar_note_link(9, "letter_drop_required") == "/calendar?row=9&field=letter_drop_required"
    assert calendar_note_link(None, "x") == "/calendar"
    comms_user = SimpleNamespace(id=2, username="comms", role="comms", active=True, tags=["comms"])
    ops = SimpleNamespace(id=3, username="ops", role="user", active=True, tags=[])
    author = SimpleNamespace(id=4, username="admin", role="admin", active=True, tags=["comms"])
    rule = SimpleNamespace(id=1, enabled=True, trigger=TRIGGER_CALENDAR_NOTE, target_tags=["comms"], target_user_ids=[])

    class _Query:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    users = [comms_user, ops, author]
    rules = [rule]
    db = SimpleNamespace(query=lambda model: _Query(rules if model.__name__ == "NotificationRule" else users))
    pairs = calendar_note_recipients(db, author_id=author.id)
    assert [u.username for u, _ in pairs] == ["comms"]


def test_pretty_tag_label():
    assert pretty_tag_label("letter-drop") == "Letter Drop"
    assert normalize_tags("Letter Drop") == ["letter-drop"]


def test_admin_tags_page_wired():
    assert "admin_tags_page" in MAIN
    assert 'href: "/admin/tags"' in COMMON
    assert 'href="/admin/tags"' in ADMIN
    assert 'id="createTagForm"' in TAGS_HTML
    assert "/api/admin/tags" in TAGS_JS
    assert "data-save-prog-tags" not in STAGES_JS
    assert "site register" in STAGES_HTML
    assert "jobTagsPicker" in INDEX
    assert "data-job-tags" in APP_JS
    assert "data-category-tags" in APP_JS
    assert "registerTagPop" in INDEX
    assert 'register-row-tags" onclick="event.stopPropagation()"' not in APP_JS
    assert 'register-program-tags" onclick="event.stopPropagation()"' not in APP_JS
    assert "renderJobTags" in APP_JS
    assert "calendar_note" in NOTIFY_ADMIN
    assert "ensure_calendar_note_rule" in NOTIFY
    assert "dispatch_calendar_note_notifications" in NOTIFY


def test_calendar_notes_ui_deep_link():
    assert 'id="calNotePanel"' in CAL_HTML
    assert 'id="calNoteForm"' in CAL_HTML
    assert "/api/calendar/comms/notes" in CAL_JS
    assert "applyDeepLink" in CAL_JS
    assert "data-cal-item" in CAL_JS
    assert "planner_link" in CAL_JS
