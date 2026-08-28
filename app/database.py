from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

BASE_DIR = Path(__file__).resolve().parent.parent


def ensure_dir(path: Path) -> Path:
    """Create a directory if possible. Never crash the app for a missing HDD mount."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path


def env_path(name: str, default: Path) -> Path:
    """Resolve an env path. Do not mkdir — a wedged HDD mount would hang import."""
    raw = (os.environ.get(name) or "").strip()
    path = Path(raw).expanduser() if raw else default
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


# App data lives under WRU_DATA_DIR (Proxmox: /opt/wru-data). Documents and
# archives stay in that tree — extra HDD env vars from v1.80 are ignored so a
# missing mount cannot take the site down.
DATA_DIR = env_path("WRU_DATA_DIR", BASE_DIR / "data")
UPLOAD_DIR = DATA_DIR / "uploads"
ARCHIVE_DIR = UPLOAD_DIR / "archived"


def build_database_url() -> str:
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]

    user = os.environ.get("POSTGRES_USER", "wru")
    password = os.environ.get("POSTGRES_PASSWORD", "wru")
    host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "wru")
    return (
        f"postgresql+psycopg2://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{db}"
    )


DATABASE_URL = build_database_url()

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    connect_args={"connect_timeout": 5},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
