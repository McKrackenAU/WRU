"""Application version helpers.

VERSION file at repo root is the source of truth (e.g. ``0.1``).
Displayed and tagged as ``v0.1``. Each push bumps the rev (0.1 → 0.2 → …).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_PATH = ROOT / "VERSION"


def read_raw_version() -> str:
    try:
        text = VERSION_PATH.read_text(encoding="utf-8").strip().splitlines()[0].strip()
        return text.lstrip("vV") or "0.1"
    except (OSError, IndexError):
        return "0.1"


def version_string() -> str:
    """Semver-ish string without prefix, e.g. ``0.1``."""
    return read_raw_version()


def version_tag() -> str:
    """Git tag / display form, e.g. ``v0.1``."""
    raw = version_string()
    return raw if raw.startswith("v") else f"v{raw}"


def bump_rev(raw: str | None = None) -> str:
    """Increment the last numeric segment: 0.1 → 0.2, 0.1.3 → 0.1.4."""
    raw = (raw or read_raw_version()).lstrip("vV")
    parts = raw.split(".")
    if not parts:
        return "0.1"
    try:
        parts[-1] = str(int(parts[-1]) + 1)
    except ValueError:
        parts.append("1")
    return ".".join(parts)
