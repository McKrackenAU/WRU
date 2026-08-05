"""Admin user management."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import (
    ADMIN_ROLE,
    USER_ROLE,
    VALID_ROLES,
    count_active_admins,
    hash_password,
    require_admin,
    user_to_public,
)
from ..database import get_db
from ..models import User

router = APIRouter(prefix="/api/admin/users", tags=["users"])


class UserCreateIn(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    display_name: str = Field(default="", max_length=128)
    password: str | None = Field(default=None, min_length=8, max_length=256)
    role: str = Field(default=USER_ROLE, pattern="^(admin|user)$")
    active: bool = True


class UserUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)
    role: str | None = Field(default=None, pattern="^(admin|user)$")
    active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=256)


def _norm_username(value: str) -> str:
    return (value or "").strip().lower()


@router.get("")
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    rows = db.query(User).order_by(User.username.asc()).all()
    return [user_to_public(u) for u in rows]


@router.post("", status_code=201)
def create_user(
    payload: UserCreateIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    username = _norm_username(payload.username)
    if len(username) < 2:
        raise HTTPException(status_code=400, detail="Username too short")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    role = payload.role if payload.role in VALID_ROLES else USER_ROLE
    password = (payload.password or "").strip() or secrets.token_urlsafe(10)
    generated = not bool((payload.password or "").strip())
    user = User(
        username=username,
        display_name=(payload.display_name or username).strip() or username,
        password_hash=hash_password(password),
        role=role,
        active=bool(payload.active),
        must_change_password=generated,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    out = user_to_public(user)
    if generated:
        out["temporary_password"] = password
    return out


@router.patch("/{user_id}")
def update_user(
    user_id: int,
    payload: UserUpdateIn,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.display_name is not None:
        user.display_name = payload.display_name.strip() or user.username

    if payload.role is not None and payload.role in VALID_ROLES:
        if user.role == ADMIN_ROLE and payload.role != ADMIN_ROLE:
            if count_active_admins(db, exclude_id=user.id) < 1 and user.active:
                raise HTTPException(status_code=400, detail="Cannot demote the last active admin")
        user.role = payload.role

    if payload.active is not None:
        if user.active and not payload.active:
            if user.role == ADMIN_ROLE and count_active_admins(db, exclude_id=user.id) < 1:
                raise HTTPException(status_code=400, detail="Cannot deactivate the last active admin")
            if user.id == actor.id:
                raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
        user.active = bool(payload.active)

    if payload.password:
        user.password_hash = hash_password(payload.password.strip())
        user.must_change_password = False

    db.commit()
    db.refresh(user)
    return user_to_public(user)


@router.post("/{user_id}/reset-password")
def reset_password(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    password = secrets.token_urlsafe(10)
    user.password_hash = hash_password(password)
    user.must_change_password = True
    db.commit()
    out = user_to_public(user)
    out["temporary_password"] = password
    return out


@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == actor.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    if user.role == ADMIN_ROLE and user.active and count_active_admins(db, exclude_id=user.id) < 1:
        raise HTTPException(status_code=400, detail="Cannot delete the last active admin")
    db.delete(user)
    db.commit()
    return None
