"""Tag-based notification rules: evaluate stage changes and fan out inbox items."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .activity import site_label, stage_label_for
from .auth import is_hidden_user
from .models import AppNotification, NotificationRule, User

MAX_TAGS = 12
MAX_TAG_LEN = 32
MAX_USER_IDS = 50
TRIGGER_STAGE_ENTERED = "stage_entered"
DEFAULT_RULE_NAME = "Structures ready for works"
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
