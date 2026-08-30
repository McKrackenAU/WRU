"""Due dates and traffic-light status for Comms form fields."""

from __future__ import annotations

from datetime import date, timedelta

from .business_days import add_business_days

DUE_SOON_DAYS = 3
STATUS_COMPLETED = "completed"
STATUS_OPEN = "open"
STATUS_OVERDUE = "overdue"
STATUS_UNSCHEDULED = "unscheduled"


def due_date_key(field_key: str) -> str:
    return f"{field_key}__due"


def due_auto_key(field_key: str) -> str:
    return f"{field_key}__due_auto"


def done_key(field_key: str) -> str:
    return f"{field_key}__done"


def parse_bool(value) -> bool:
    if value is True or value == 1:
        return True
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def parse_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def is_done(form_values: dict | None, field_key: str) -> bool:
    return parse_bool((form_values or {}).get(done_key(field_key)))


def uses_auto_due(field, form_values: dict | None) -> bool:
    raw = (form_values or {}).get(due_auto_key(getattr(field, "field_key", "")))
    if raw is None or raw == "":
        return getattr(field, "offset_days", None) is not None
    return parse_bool(raw)


def compute_auto_due(field, site) -> date | None:
    offset = getattr(field, "offset_days", None)
    start = getattr(site, "indicative_site_start_date", None) if site is not None else None
    if offset is None or start is None:
        return None
    try:
        return add_business_days(start, -int(offset))
    except (TypeError, ValueError):
        return None


def resolve_due_date(field, form_values: dict | None, site) -> date | None:
    if not getattr(field, "track_due", False):
        return None
    if uses_auto_due(field, form_values):
        auto = compute_auto_due(field, site)
        if auto:
            return auto
    return parse_date((form_values or {}).get(due_date_key(getattr(field, "field_key", ""))))


def item_status(done: bool, due: date | None, today: date | None = None) -> str:
    if done:
        return STATUS_COMPLETED
    if due is None:
        return STATUS_UNSCHEDULED
    today = today or date.today()
    if due < today:
        return STATUS_OVERDUE
    return STATUS_OPEN


def should_notify_status(status: str, due: date | None, today: date | None = None, lead_days: int = DUE_SOON_DAYS) -> bool:
    today = today or date.today()
    if status == STATUS_OVERDUE:
        return True
    if status == STATUS_OPEN and due is not None:
        return due <= today + timedelta(days=max(0, int(lead_days)))
    return False


def calendar_color(status: str) -> str:
    if status == STATUS_COMPLETED:
        return "green"
    if status == STATUS_OVERDUE:
        return "red"
    if status == STATUS_OPEN:
        return "yellow"
    return "gray"


def build_calendar_item(field, row, site, today: date | None = None) -> dict | None:
    if not getattr(field, "track_due", False):
        return None
    form_values = getattr(row, "form_values", None) or {}
    due = resolve_due_date(field, form_values, site)
    done = is_done(form_values, field.field_key)
    if due is None and not done:
        return None
    status = item_status(done, due, today)
    road = (getattr(site, "road_name", None) or "").strip() if site else ""
    number = (getattr(site, "site_number", None) or "").strip() if site else ""
    label = f"{road} - {number}" if number else (road or (getattr(row, "section", None) or "Comms row"))
    return {
        "row_id": getattr(row, "id", None),
        "sheet_id": getattr(row, "sheet_id", None),
        "site_id": getattr(row, "site_id", None) or getattr(site, "id", None),
        "field_id": getattr(field, "id", None),
        "field_key": field.field_key,
        "field_name": field.name,
        "title": f"{field.name} · {label}",
        "due_date": due.isoformat() if due else None,
        "done": done,
        "auto": uses_auto_due(field, form_values),
        "offset_days": getattr(field, "offset_days", None),
        "status": status,
        "color": calendar_color(status),
        "program": (getattr(site, "program", None) or "").strip() if site else "",
        "link": f"/comms?row={int(row.id)}" if getattr(row, "id", None) else "/calendar",
    }
