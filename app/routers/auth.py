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


@router.post("/change-password")
def change_password(
    payload: PasswordChangeIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(payload.new_password.strip()) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    user.password_hash = hash_password(payload.new_password.strip())
    user.must_change_password = False
    db.commit()
    db.refresh(user)
    set_session_user(request, user)
    return {"ok": True, "user": user_to_public(user)}
