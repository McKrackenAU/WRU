"""Inbox notifications for signed-in users, and admin rule CRUD."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_admin, user_to_public
from ..database import get_db
from ..models import AppNotification, NotificationRule, User
from ..notify import (
    TRIGGER_COMMS_DUE,
    TRIGGER_STAGE_ENTERED,
    mark_read_now,
    normalize_tags,
    normalize_user_ids,
    notification_to_public,
)

inbox_router = APIRouter(prefix="/api/notifications", tags=["notifications"])
admin_router = APIRouter(
    prefix="/api/admin/notification-rules",
    tags=["notification-rules"],
    dependencies=[Depends(require_admin)],
)


def _rule_to_public(rule: NotificationRule) -> dict:
    return {
        "id": rule.id,
        "name": rule.name,
        "enabled": bool(rule.enabled),
        "trigger": rule.trigger or TRIGGER_STAGE_ENTERED,
        "stage_key": rule.stage_key or "",
        "program": rule.program or "",
        "target_tags": normalize_tags(rule.target_tags),
        "target_user_ids": normalize_user_ids(rule.target_user_ids),
        "message_template": rule.message_template or "",
    }


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    trigger: str = Field(default=TRIGGER_STAGE_ENTERED, max_length=32)
    stage_key: str = Field(default="", max_length=64)
    program: str = Field(default="", max_length=128)
    target_tags: list[str] | str = Field(default_factory=list)
    target_user_ids: list[int] = Field(default_factory=list)
    message_template: str = Field(default="", max_length=4000)


class RulePatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    enabled: bool | None = None
    trigger: str | None = Field(default=None, max_length=32)
    stage_key: str | None = Field(default=None, max_length=64)
    program: str | None = Field(default=None, max_length=128)
    target_tags: list[str] | str | None = None
    target_user_ids: list[int] | None = None
    message_template: str | None = Field(default=None, max_length=4000)


def _apply_rule_fields(rule: NotificationRule, payload: RuleIn | RulePatchIn, *, creating: bool) -> None:
    data = payload.model_dump(exclude_unset=not creating)
    if "name" in data and data["name"] is not None:
        rule.name = (data["name"] or "").strip() or "Notification rule"
    if "enabled" in data and data["enabled"] is not None:
        rule.enabled = bool(data["enabled"])
    if "trigger" in data and data["trigger"] is not None:
        trigger = (data["trigger"] or TRIGGER_STAGE_ENTERED).strip() or TRIGGER_STAGE_ENTERED
        rule.trigger = trigger
    if "stage_key" in data and data["stage_key"] is not None:
        rule.stage_key = (data["stage_key"] or "").strip()
    if "program" in data and data["program"] is not None:
        rule.program = (data["program"] or "").strip()
    if "target_tags" in data and data["target_tags"] is not None:
        rule.target_tags = normalize_tags(data["target_tags"])
    if "target_user_ids" in data and data["target_user_ids"] is not None:
        rule.target_user_ids = normalize_user_ids(data["target_user_ids"])
    if "message_template" in data and data["message_template"] is not None:
        rule.message_template = (data["message_template"] or "").strip()


@inbox_router.get("")
def list_my_notifications(
    limit: int = Query(default=40, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    unread = (
        db.query(func.count(AppNotification.id))
        .filter(AppNotification.user_id == user.id, AppNotification.read_at.is_(None))
        .scalar()
        or 0
    )
    rows = (
        db.query(AppNotification)
        .filter(AppNotification.user_id == user.id)
        .order_by(AppNotification.created_at.desc(), AppNotification.id.desc())
        .limit(limit)
        .all()
    )
    return {"items": [notification_to_public(r) for r in rows], "unread_count": int(unread)}


@inbox_router.post("/{notification_id}/read")
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = (
        db.query(AppNotification)
        .filter(AppNotification.id == notification_id, AppNotification.user_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Notification not found")
    if not row.read_at:
        row.read_at = mark_read_now()
        db.commit()
        db.refresh(row)
    return notification_to_public(row)


@inbox_router.post("/read-all")
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    now = mark_read_now()
    updated = (
        db.query(AppNotification)
        .filter(AppNotification.user_id == user.id, AppNotification.read_at.is_(None))
        .update({AppNotification.read_at: now}, synchronize_session=False)
    )
    db.commit()
    return {"updated": int(updated or 0)}


@admin_router.get("")
def list_rules(db: Session = Depends(get_db)):
    rows = db.query(NotificationRule).order_by(NotificationRule.id.asc()).all()
    return [_rule_to_public(r) for r in rows]


@admin_router.get("/options")
def rule_options(db: Session = Depends(get_db)):
    users = (
        db.query(User)
        .filter(User.username != "root")
        .order_by(User.username.asc())
        .all()
    )
    return {"users": [user_to_public(u) for u in users]}


@admin_router.post("", status_code=201)
def create_rule(payload: RuleIn, db: Session = Depends(get_db)):
    rule = NotificationRule(
        name="Notification rule",
        enabled=True,
        trigger=TRIGGER_STAGE_ENTERED,
        stage_key="",
        program="",
        target_tags=[],
        target_user_ids=[],
        message_template="",
    )
    _apply_rule_fields(rule, payload, creating=True)
    if rule.trigger != TRIGGER_COMMS_DUE and not rule.stage_key:
        raise HTTPException(status_code=400, detail="Choose a stage trigger")
    if not normalize_tags(rule.target_tags) and not normalize_user_ids(rule.target_user_ids):
        raise HTTPException(status_code=400, detail="Add at least one tag or user to notify")
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _rule_to_public(rule)


@admin_router.patch("/{rule_id}")
def update_rule(rule_id: int, payload: RulePatchIn, db: Session = Depends(get_db)):
    rule = db.get(NotificationRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    _apply_rule_fields(rule, payload, creating=False)
    if rule.trigger != TRIGGER_COMMS_DUE and not (rule.stage_key or "").strip():
        raise HTTPException(status_code=400, detail="Choose a stage trigger")
    if not normalize_tags(rule.target_tags) and not normalize_user_ids(rule.target_user_ids):
        raise HTTPException(status_code=400, detail="Add at least one tag or user to notify")
    db.commit()
    db.refresh(rule)
    return _rule_to_public(rule)


@admin_router.delete("/{rule_id}", status_code=204)
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.get(NotificationRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()
    return None
