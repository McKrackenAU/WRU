"""Login / logout / current user."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import (
    authenticate,
    clear_session,
    get_current_user,
    hash_password,
    is_hidden_user,
    new_password_error,
    set_session_user,
    user_to_public,
    verify_password,
)
from ..database import get_db
from ..models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class MeUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    prefs: dict | None = None


@router.post("/login")
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    user = authenticate(db, payload.username, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    set_session_user(request, user)
    return {"ok": True, "user": user_to_public(user)}


@router.post("/logout")
def logout(request: Request):
    clear_session(request)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return user_to_public(user)


@router.patch("/me")
def update_me(
    payload: MeUpdateIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from ..user_prefs import normalize_prefs

    if is_hidden_user(user) and payload.display_name is not None:
        raise HTTPException(status_code=400, detail="The recovery account name cannot be edited here")
    if payload.display_name is not None:
        name = payload.display_name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Display name is required")
        user.display_name = name
    if payload.prefs is not None:
        current = user.prefs if isinstance(user.prefs, dict) else {}
        incoming = payload.prefs if isinstance(payload.prefs, dict) else {}
        merged = {**current, **incoming}
        cur_colors = current.get("colors") if isinstance(current.get("colors"), dict) else {}
        in_colors = incoming.get("colors") if isinstance(incoming.get("colors"), dict) else {}
        merged["colors"] = {**cur_colors, **in_colors}
        user.prefs = normalize_prefs(merged)
    db.commit()
    db.refresh(user)
    set_session_user(request, user)
    return user_to_public(user)


@router.post("/change-password")
def change_password(
    payload: PasswordChangeIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if is_hidden_user(user):
        raise HTTPException(status_code=400, detail="The recovery account password cannot be changed")
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    problem = new_password_error(payload.new_password, payload.current_password)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    user.password_hash = hash_password(payload.new_password.strip())
    user.must_change_password = False
    db.commit()
    db.refresh(user)
    set_session_user(request, user)
    return {"ok": True, "user": user_to_public(user)}
