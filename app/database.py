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


DATA_DIR = ensure_dir(Path(os.environ.get("WRU_DATA_DIR", BASE_DIR / "data")))


def _env_dir(name: str, default: Path) -> Path:
    raw = (os.environ.get(name) or "").strip()
    path = Path(raw).expanduser() if raw else default
    if not path.is_absolute():
        path = (BASE_DIR / path).resolve()
    return ensure_dir(path)


# Documents on HDD: set WRU_UPLOAD_DIR (live) and WRU_ARCHIVE_DIR (archived sites).
# Postgres stays on whatever disk DATABASE_URL points at (typically NVMe).
UPLOAD_DIR = _env_dir("WRU_UPLOAD_DIR", DATA_DIR / "uploads")
ARCHIVE_DIR = _env_dir("WRU_ARCHIVE_DIR", UPLOAD_DIR / "archived")


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
