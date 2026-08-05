"""Map basemap configuration (Nearmap API key).

Key resolution order:
1. ``NEARMAP_API_KEY`` environment variable (locks admin overwrite if set)
2. File under ``WRU_DATA_DIR`` / ``nearmap_api_key``
"""

from __future__ import annotations

import os
from pathlib import Path

from .database import DATA_DIR

KEY_FILE = DATA_DIR / "nearmap_api_key"
ENV_KEY = "NEARMAP_API_KEY"


def env_nearmap_key() -> str | None:
    raw = (os.environ.get(ENV_KEY) or "").strip()
    return raw or None


def file_nearmap_key() -> str | None:
    try:
        if KEY_FILE.is_file():
            raw = KEY_FILE.read_text(encoding="utf-8").strip().splitlines()[0].strip()
            return raw or None
    except OSError:
        return None
    return None


def get_nearmap_api_key() -> str | None:
    return env_nearmap_key() or file_nearmap_key()


def nearmap_key_source() -> str | None:
    if env_nearmap_key():
        return "env"
    if file_nearmap_key():
        return "file"
    return None


def set_nearmap_api_key(value: str | None) -> None:
    """Persist key to DATA_DIR. Raises if env var is set (env wins)."""
    if env_nearmap_key():
        raise PermissionError(
            f"{ENV_KEY} is set on the server — clear the env var to manage the key in the UI."
        )
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    text = (value or "").strip()
    if not text:
        try:
            KEY_FILE.unlink(missing_ok=True)
        except OSError as exc:
            raise RuntimeError(f"Could not remove Nearmap key file: {exc}") from exc
        return
    KEY_FILE.write_text(text + "\n", encoding="utf-8")
    try:
        KEY_FILE.chmod(0o600)
    except OSError:
        pass


def map_config_public() -> dict:
    key = get_nearmap_api_key()
    return {
        "nearmap_configured": bool(key),
        "nearmap_api_key": key,  # used client-side for tile URL (same approach as VenInspect)
        "nearmap_key_source": nearmap_key_source(),
        "providers": ["osm"] + (["nearmap"] if key else []),
        "default_provider": "osm",
    }
