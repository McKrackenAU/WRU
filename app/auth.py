"""Session-cookie authentication for WRU."""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

import bcrypt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .database import DATA_DIR, SessionLocal, get_db
from .models import User

ADMIN_ROLE = "admin"
USER_ROLE = "user"
VALID_ROLES = {ADMIN_ROLE, USER_ROLE}
BOOTSTRAP_FILE = DATA_DIR / "bootstrap_admin.txt"


def secret_key() -> str:
    key = (os.environ.get("WRU_SECRET_KEY") or "").strip()
    if key:
        return key
    # Dev fallback — installs should always set WRU_SECRET_KEY
    return "dev-only-change-me-wru-secret"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            (password_hash or "").encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False


def user_to_public(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name or user.username,
        "role": user.role,
        "active": bool(user.active),
        "must_change_password": bool(user.must_change_password),
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


def set_session_user(request: Request, user: User) -> None:
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["username"] = user.username
    request.session["display_name"] = user.display_name or user.username
    request.session["role"] = user.role
    request.session["must_change_password"] = bool(user.must_change_password)


def clear_session(request: Request) -> None:
    request.session.clear()


def session_user_id(request: Request) -> int | None:
    raw = request.session.get("user_id")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def authenticate(db: Session, username: str, password: str) -> User | None:
    uname = (username or "").strip().lower()
    if not uname or not password:
        return None
    user = db.query(User).filter(User.username == uname).first()
    if not user or not user.active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return user


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    uid = session_user_id(request)
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = get_user_by_id(db, uid)
    if not user or not user.active:
        clear_session(request)
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != ADMIN_ROLE:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def count_active_admins(db: Session, *, exclude_id: int | None = None) -> int:
    q = db.query(User).filter(User.role == ADMIN_ROLE, User.active.is_(True))
    if exclude_id is not None:
        q = q.filter(User.id != exclude_id)
    return q.count()


def ensure_admin_user(db: Session | None = None) -> None:
    """Create the first admin from env if the users table is empty."""
    owns = db is None
    if owns:
        db = SessionLocal()
    try:
        if db.query(User).count() > 0:
            return
        username = (os.environ.get("WRU_ADMIN_USER") or "admin").strip().lower() or "admin"
        display = (os.environ.get("WRU_ADMIN_NAME") or "Administrator").strip() or "Administrator"
        password = (os.environ.get("WRU_ADMIN_PASSWORD") or "").strip()
        generated = False
        if not password:
            password = secrets.token_urlsafe(12)
            generated = True
        user = User(
            username=username,
            display_name=display,
            password_hash=hash_password(password),
            role=ADMIN_ROLE,
            active=True,
            must_change_password=True,
        )
        db.add(user)
        db.commit()
        try:
            BOOTSTRAP_FILE.parent.mkdir(parents=True, exist_ok=True)
            BOOTSTRAP_FILE.write_text(
                "Bootstrap admin created.\n"
                f"username={username}\n"
                f"password={password}\n"
                "Change this password after first login.\n",
                encoding="utf-8",
            )
            try:
                BOOTSTRAP_FILE.chmod(0o600)
            except OSError:
                pass
        except OSError:
            pass
        print(
            f"[WRU] Created bootstrap admin '{username}'. "
            f"{'Password in ' + str(BOOTSTRAP_FILE) if generated else 'Using WRU_ADMIN_PASSWORD from environment.'}"
        )
    finally:
        if owns and db is not None:
            db.close()


def is_public_path(path: str) -> bool:
    if path.startswith("/static/"):
        return True
    if path in {"/login", "/favicon.ico", "/api/auth/login", "/api/auth/logout"}:
        return True
    return False


def is_password_change_allowed_path(path: str) -> bool:
    """Paths allowed while must_change_password is set on the session."""
    return path in {
        "/login",
        "/api/auth/change-password",
        "/api/auth/logout",
        "/api/auth/me",
    }


def is_admin_path(path: str, method: str = "GET") -> bool:
    if path.startswith("/admin"):
        return True
    if path.startswith("/api/admin"):
        return True
    if path.startswith("/api/system"):
        return True
    if path.startswith("/api/import"):
        return True
    # Nearmap key write is admin-only; read config is ok for ops map users
    if path == "/api/map/nearmap-key" and method.upper() in {"PUT", "POST", "PATCH", "DELETE"}:
        return True
    # Rate / cost-settings mutations are admin console work
    if method.upper() in {"PUT", "POST", "PATCH", "DELETE"}:
        if path == "/api/costs/settings":
            return True
        if path == "/api/costs/rates" or path.startswith("/api/costs/rates/"):
            return True
    return False
