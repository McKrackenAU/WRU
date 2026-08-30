"""Tag-based notification rules: evaluate stage changes and fan out inbox items."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .activity import site_label, stage_label_for
from .auth import COMMS_ROLE, is_hidden_user
from .models import AppNotification, NotificationRule, ProgramCategory, Site, TagDef, User

MAX_TAGS = 12
MAX_TAG_LEN = 32
MAX_USER_IDS = 50
TRIGGER_STAGE_ENTERED = "stage_entered"
TRIGGER_COMMS_DUE = "comms_due"
TRIGGER_CALENDAR_NOTE = "calendar_note"
DEFAULT_RULE_NAME = "Structures ready for works"
COMMS_DUE_RULE_NAME = "Comms item due"
CALENDAR_NOTE_RULE_NAME = "Calendar note"
DEFAULT_LIBRARY_TAGS = (("structures", "Structures"), ("comms", "Comms"))
STAGELESS_TRIGGERS = {TRIGGER_COMMS_DUE, TRIGGER_CALENDAR_NOTE}
_PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}", re.IGNORECASE)


def normalize_tags(raw) -> list[str]:
    """Lowercase, unique tags; drop empties; cap length and count."""
    seen: set[str] = set()
    out: list[str] = []
    if raw is None:
        return out
    if isinstance(raw, str):
        parts = raw.replace(";", ",").split(",")
    elif isinstance(raw, (list, tuple, set)):
        parts = list(raw)
    else:
        return out
    for part in parts:
        tag = re.sub(r"[^a-z0-9_-]+", "", str(part or "").strip().lower().replace(" ", "-"))
        tag = tag[:MAX_TAG_LEN].strip("-_")
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
        if len(out) >= MAX_TAGS:
            break
    return out


def normalize_user_ids(raw) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    if raw is None:
        return out
    items = raw if isinstance(raw, (list, tuple, set)) else [raw]
    for item in items:
        try:
            uid = int(item)
        except (TypeError, ValueError):
            continue
        if uid <= 0 or uid in seen:
            continue
        seen.add(uid)
        out.append(uid)
        if len(out) >= MAX_USER_IDS:
            break
    return out


def user_tag_set(user) -> set[str]:
    return set(normalize_tags(getattr(user, "tags", None)))


def merge_tag_lists(*groups) -> list[str]:
    """Union of tag lists, preserving first-seen order."""
    combined: list[str] = []
    for group in groups:
        combined.extend(normalize_tags(group))
    return normalize_tags(combined)


def program_tag_map(db: Session) -> dict[str, list[str]]:
    """Lowercased program name → category tags."""
    out: dict[str, list[str]] = {}
    for row in db.query(ProgramCategory).all():
        name = (row.name or "").strip().lower()
        if name:
            out[name] = normalize_tags(getattr(row, "tags", None))
    return out


def category_tags_for_program(db: Session | None, program: str | None) -> list[str]:
    if db is None or not (program or "").strip():
        return []
    want = program.strip().lower()
    for row in db.query(ProgramCategory).all():
        if (row.name or "").strip().lower() == want:
            return normalize_tags(getattr(row, "tags", None))
    return []


def effective_job_tags(site, category_tags=None) -> list[str]:
    """Job-specific tags plus inherited category tags."""
    return merge_tag_lists(category_tags, getattr(site, "tags", None))


def tag_to_public(row: TagDef) -> dict:
    return {
        "id": row.id,
        "slug": row.slug,
        "label": row.label or row.slug,
        "position": row.position,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def pretty_tag_label(slug: str) -> str:
    return (slug or "").replace("-", " ").replace("_", " ").title() or slug


def ensure_tag_seed(db: Session) -> None:
    """Seed the library with defaults plus any tags already on users."""
    existing = {row.slug for row in db.query(TagDef).all()}
    wanted: list[tuple[str, str]] = list(DEFAULT_LIBRARY_TAGS)
    seen = {slug for slug, _ in wanted}
    for user in db.query(User).all():
        for slug in normalize_tags(getattr(user, "tags", None)):
            if slug not in seen:
                wanted.append((slug, pretty_tag_label(slug)))
                seen.add(slug)
    changed = False
    position = 0
    for slug, label in wanted:
        position += 10
        if slug in existing:
            continue
        db.add(TagDef(slug=slug, label=label, position=position))
        existing.add(slug)
        changed = True
    if changed:
        db.commit()


def retarget_tag_slug(db: Session, old_slug: str, new_slug: str) -> None:
    """Rewrite a renamed library slug on users, jobs, categories, and rules."""
    old = (old_slug or "").strip().lower()
    new = (new_slug or "").strip().lower()
    if not old or not new or old == new:
        return

    def rewrite(raw):
        tags = normalize_tags(raw)
        return normalize_tags([new if tag == old else tag for tag in tags])

    for user in db.query(User).all():
        tags = normalize_tags(getattr(user, "tags", None))
        if old in tags:
            user.tags = rewrite(tags)
    for site in db.query(Site).all():
        tags = normalize_tags(getattr(site, "tags", None))
        if old in tags:
            site.tags = rewrite(tags)
    for cat in db.query(ProgramCategory).all():
        tags = normalize_tags(getattr(cat, "tags", None))
        if old in tags:
            cat.tags = rewrite(tags)
    for rule in db.query(NotificationRule).all():
        tags = normalize_tags(getattr(rule, "target_tags", None))
        if old in tags:
            rule.target_tags = rewrite(tags)


def user_matches_rule(user, rule) -> bool:
    """True if the user has any target tag or is named on the rule."""
    if user is None:
        return False
    uid = getattr(user, "id", None)
    target_ids = set(normalize_user_ids(getattr(rule, "target_user_ids", None)))
    if uid is not None and int(uid) in target_ids:
        return True
    wanted = set(normalize_tags(getattr(rule, "target_tags", None)))
    if not wanted:
        return False
    return bool(user_tag_set(user) & wanted)


def rule_matches_event(rule, site, before: str | None, after: str | None) -> bool:
    if not getattr(rule, "enabled", True):
        return False
    if (getattr(rule, "trigger", None) or TRIGGER_STAGE_ENTERED) != TRIGGER_STAGE_ENTERED:
        return False
    if not after or before == after:
        return False
    wanted_stage = (getattr(rule, "stage_key", None) or "").strip()
    if wanted_stage and wanted_stage != after:
        return False
    wanted_program = (getattr(rule, "program", None) or "").strip()
    if wanted_program:
        site_program = (getattr(site, "program", None) or "").strip()
        if site_program.lower() != wanted_program.lower():
            return False
    return True


def planned_notifications(rules, users, site, before: str | None, after: str | None) -> list[tuple]:
    """Return (user, rule) pairs that should receive an inbox item."""
    if not after or before == after:
        return []
    out: list[tuple] = []
    seen: set[tuple[int, int]] = set()
    for rule in rules or []:
        if not rule_matches_event(rule, site, before, after):
            continue
        rule_id = getattr(rule, "id", None)
        for user in users or []:
            if not getattr(user, "active", True):
                continue
            if is_hidden_user(user):
                continue
            if not user_matches_rule(user, rule):
                continue
            uid = getattr(user, "id", None)
            key = (int(uid) if uid is not None else id(user), int(rule_id) if rule_id is not None else id(rule))
            if key in seen:
                continue
            seen.add(key)
            out.append((user, rule))
    return out


def _template_values(site, stage_key: str, stage_label: str) -> dict[str, str]:
    road = (getattr(site, "road_name", None) or "").strip()
    number = (getattr(site, "site_number", None) or "").strip()
    program = (getattr(site, "program", None) or "").strip()
    label = site_label(site)
    return {
        "site": label,
        "label": label,
        "road": road or "Unknown road",
        "site_number": number,
        "program": program or "Unassigned",
        "stage": stage_label,
        "stage_key": stage_key or "",
    }


def render_body(template: str | None, site, stage_key: str, stage_label: str) -> str:
    values = _template_values(site, stage_key, stage_label)
    raw = (template or "").strip()
    if not raw:
        program = values["program"]
        return f"{program} job {values['site']} entered {stage_label}."
    def repl(match: re.Match) -> str:
        return values.get(match.group(1).lower(), match.group(0))
    return _PLACEHOLDER_RE.sub(repl, raw)[:4000]


def render_title(site, stage_label: str) -> str:
    return f"{site_label(site)} — {stage_label}"[:255]


def notification_link(site) -> str:
    site_id = getattr(site, "id", None)
    if not site_id:
        return "/"
    return f"/?highlight={int(site_id)}"


def ensure_default_notification_rules(db: Session) -> None:
    if db.query(NotificationRule).first():
        return
    db.add(
        NotificationRule(
            name=DEFAULT_RULE_NAME,
            enabled=True,
            trigger=TRIGGER_STAGE_ENTERED,
            stage_key="ready_for_works",
            program="Structures",
            target_tags=["structures"],
            target_user_ids=[],
            message_template="",
        )
    )
    db.commit()


def ensure_calendar_note_rule(db: Session) -> None:
    existing = (
        db.query(NotificationRule)
        .filter(NotificationRule.trigger == TRIGGER_CALENDAR_NOTE)
        .first()
    )
    if existing:
        return
    db.add(
        NotificationRule(
            name=CALENDAR_NOTE_RULE_NAME,
            enabled=True,
            trigger=TRIGGER_CALENDAR_NOTE,
            stage_key="",
            program="",
            target_tags=["comms"],
            target_user_ids=[],
            message_template="{author} left a note on {item}: {note}",
        )
    )
    db.commit()


def calendar_note_link(row_id: int | None, field_key: str | None) -> str:
    if not row_id or not field_key:
        return "/calendar"
    return f"/calendar?row={int(row_id)}&field={field_key}"


def calendar_note_recipients(db: Session, *, author_id: int | None = None) -> list[tuple]:
    """Users who should hear about a calendar note: matching rules, comms role, or comms tag."""
    rules = [
        rule
        for rule in db.query(NotificationRule).all()
        if getattr(rule, "enabled", True) and (rule.trigger or "") == TRIGGER_CALENDAR_NOTE
    ]
    users = db.query(User).all()
    out: list[tuple] = []
    seen: set[int] = set()
    for user in users:
        uid = getattr(user, "id", None)
        if uid is None or int(uid) in seen:
            continue
        if author_id is not None and int(uid) == int(author_id):
            continue
        if not getattr(user, "active", True) or is_hidden_user(user):
            continue
        matched_rule = None
        for rule in rules:
            if user_matches_rule(user, rule):
                matched_rule = rule
                break
        role_comms = (getattr(user, "role", None) or "") == COMMS_ROLE
        tagged_comms = "comms" in user_tag_set(user)
        if not matched_rule and not role_comms and not tagged_comms:
            continue
        seen.add(int(uid))
        out.append((user, matched_rule or (rules[0] if rules else None)))
    return out


def dispatch_calendar_note_notifications(
    db: Session,
    *,
    note,
    row,
    field,
    site=None,
    author=None,
) -> int:
    """Fan out inbox items for a new calendar note. Caller commits. No unread-title dedup."""
    author_id = getattr(author, "id", None)
    pairs = calendar_note_recipients(db, author_id=author_id)
    if not pairs:
        return 0
    author_name = (
        (getattr(author, "display_name", None) or getattr(author, "username", None) or "")
        or getattr(note, "created_by", None)
        or "Someone"
    ).strip() or "Someone"
    field_name = (getattr(field, "name", None) or getattr(field, "field_key", None) or "item").strip()
    site_name = site_label(site) if site is not None else (getattr(row, "section", None) or "Comms row")
    title = f"{author_name} commented on {field_name} · {site_name}"[:255]
    note_body = (getattr(note, "body", None) or "").strip()
    link = calendar_note_link(getattr(row, "id", None), getattr(field, "field_key", None))
    site_id = getattr(site, "id", None) or getattr(row, "site_id", None)
    created = 0
    for user, rule in pairs:
        body = (getattr(rule, "message_template", None) or "").strip() if rule is not None else ""
        if body:
            body = (
                body.replace("{author}", author_name)
                .replace("{item}", field_name)
                .replace("{field}", field_name)
                .replace("{note}", note_body)
                .replace("{site}", site_name)
            )
        else:
            body = f"{author_name} left a note on {field_name} · {site_name}: {note_body}"
        db.add(
            AppNotification(
                user_id=user.id,
                rule_id=getattr(rule, "id", None) if rule is not None else None,
                site_id=site_id,
                title=title,
                body=body[:4000],
                link=link,
            )
        )
        created += 1
    return created


def ensure_comms_due_rule(db: Session) -> None:
    existing = (
        db.query(NotificationRule)
        .filter(NotificationRule.trigger == TRIGGER_COMMS_DUE)
        .first()
    )
    if existing:
        return
    db.add(
        NotificationRule(
            name=COMMS_DUE_RULE_NAME,
            enabled=True,
            trigger=TRIGGER_COMMS_DUE,
            stage_key="",
            program="",
            target_tags=["comms"],
            target_user_ids=[],
            message_template="{item} is {status} ({due}).",
        )
    )
    db.commit()


def _comms_due_rules(db: Session) -> list[NotificationRule]:
    return [
        rule
        for rule in db.query(NotificationRule).all()
        if getattr(rule, "enabled", True) and (rule.trigger or "") == TRIGGER_COMMS_DUE
    ]


def dispatch_comms_due_notifications(db: Session, *, row=None, site=None) -> int:
    """Flag comms-tagged users when a tracked item is due soon or overdue. Caller commits."""
    from .comms_due import (
        DUE_SOON_DAYS,
        build_calendar_item,
        should_notify_status,
    )
    from .models import CommsRow, CommsTemplateField, Site

    rules = _comms_due_rules(db)
    if not rules:
        return 0
    fields = (
        db.query(CommsTemplateField)
        .filter(CommsTemplateField.track_due.is_(True))
        .all()
    )
    if not fields:
        return 0
    rows = []
    if row is not None:
        rows = [row]
    elif site is not None and getattr(site, "id", None):
        rows = db.query(CommsRow).filter(CommsRow.site_id == site.id).all()
    if not rows:
        return 0
    users = db.query(User).all()
    created = 0
    for current in rows:
        linked = site
        if linked is None and getattr(current, "site_id", None):
            linked = db.get(Site, current.site_id)
        program = (getattr(linked, "program", None) or "").strip().lower()
        for field in fields:
            item = build_calendar_item(field, current, linked)
            if not item or not should_notify_status(item["status"], parse_due(item.get("due_date")), lead_days=DUE_SOON_DAYS):
                continue
            for rule in rules:
                wanted_program = (rule.program or "").strip()
                if wanted_program and wanted_program.lower() != program:
                    continue
                for user in users:
                    if not getattr(user, "active", True) or is_hidden_user(user):
                        continue
                    if not user_matches_rule(user, rule):
                        continue
                    already = (
                        db.query(AppNotification)
                        .filter(
                            AppNotification.user_id == user.id,
                            AppNotification.rule_id == rule.id,
                            AppNotification.site_id == item.get("site_id"),
                            AppNotification.read_at.is_(None),
                            AppNotification.title == item["title"][:255],
                        )
                        .first()
                    )
                    if already:
                        continue
                    status_label = "overdue" if item["status"] == "overdue" else "due soon"
                    due_label = item["due_date"] or "no date"
                    body = (rule.message_template or "").strip()
                    if body:
                        body = (
                            body.replace("{item}", item["title"])
                            .replace("{status}", status_label)
                            .replace("{due}", due_label)
                            .replace("{site}", item["title"].split(" · ")[-1])
                        )
                    else:
                        body = f"{item['title']} is {status_label} ({due_label})."
                    db.add(
                        AppNotification(
                            user_id=user.id,
                            rule_id=rule.id,
                            site_id=item.get("site_id"),
                            title=item["title"][:255],
                            body=body[:4000],
                            link=item.get("link") or "/calendar",
                        )
                    )
                    created += 1
    return created


def parse_due(value) -> date | None:
    from datetime import date as date_cls

    if not value:
        return None
    if isinstance(value, date_cls):
        return value
    try:
        return date_cls.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def dispatch_stage_notifications(db: Session, site, before: str | None, after: str | None) -> int:
    """Create inbox rows for matching rules. Caller commits."""
    pairs = planned_notifications(
        db.query(NotificationRule).all(),
        db.query(User).all(),
        site,
        before,
        after,
    )
    if not pairs:
        return 0
    stage_label = stage_label_for(db, after)
    created = 0
    for user, rule in pairs:
        already = (
            db.query(AppNotification)
            .filter(
                AppNotification.user_id == user.id,
                AppNotification.rule_id == rule.id,
                AppNotification.site_id == getattr(site, "id", None),
                AppNotification.read_at.is_(None),
            )
            .first()
        )
        if already:
            continue
        db.add(
            AppNotification(
                user_id=user.id,
                rule_id=rule.id,
                site_id=getattr(site, "id", None),
                title=render_title(site, stage_label),
                body=render_body(getattr(rule, "message_template", None), site, after or "", stage_label),
                link=notification_link(site),
            )
        )
        created += 1
    return created


def notification_to_public(row: AppNotification) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "body": row.body,
        "link": row.link or "/",
        "site_id": row.site_id,
        "rule_id": row.rule_id,
        "read": bool(row.read_at),
        "read_at": row.read_at.isoformat() if row.read_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def mark_read_now() -> datetime:
    return datetime.now(timezone.utc)
