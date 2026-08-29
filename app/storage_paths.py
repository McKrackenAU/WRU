"""Resolve configurable file storage roots for future HDD / NAS deploys."""

from __future__ import annotations

from pathlib import Path

from .database import DATA_DIR

DOCUMENTS = "documents"
COST_ESTIMATES = "cost_estimates"
KML = "kml"
BACKUPS = "backups"

STORAGE_KINDS = (DOCUMENTS, COST_ESTIMATES, KML, BACKUPS)

STORAGE_META = {
    DOCUMENTS: {
        "label": "Documents",
        "hint": "Site register files, comms notices, and the document library.",
        "default_relative": "uploads",
    },
    COST_ESTIMATES: {
        "label": "Cost estimate attachments",
        "hint": "Quotes and files attached to traffic cost estimates.",
        "default_relative": "uploads/cost-estimates",
    },
    KML: {
        "label": "Map layers (KML)",
        "hint": "Imported KML / markup layers.",
        "default_relative": "uploads/kml",
    },
    BACKUPS: {
        "label": "Backup staging",
        "hint": "Temporary folder used while building or restoring a server backup.",
        "default_relative": "backups",
    },
}


def default_dir(kind: str) -> Path:
    meta = STORAGE_META.get(kind) or STORAGE_META[DOCUMENTS]
    return DATA_DIR / meta["default_relative"]


def coerce_dir(kind: str, raw: str | None) -> Path:
    text = (raw or "").strip()
    if not text:
        path = default_dir(kind)
    else:
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = (DATA_DIR / path).resolve()
        else:
            path = path.resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _configured_path(kind: str) -> str:
    if kind not in STORAGE_META:
        return ""
    try:
        from .database import SessionLocal
        from .models import StorageLocation
    except Exception:
        return ""
    db = SessionLocal()
    try:
        row = db.query(StorageLocation).filter(StorageLocation.key == kind).first()
        return (row.path if row else "") or ""
    except Exception:
        return ""
    finally:
        db.close()


def resolve_dir(kind: str) -> Path:
    return coerce_dir(kind, _configured_path(kind))


def documents_dir() -> Path:
    return resolve_dir(DOCUMENTS)


def cost_estimates_dir() -> Path:
    return resolve_dir(COST_ESTIMATES)


def kml_dir() -> Path:
    return resolve_dir(KML)


def backups_dir() -> Path:
    return resolve_dir(BACKUPS)


def describe_locations(db) -> list[dict]:
    from .models import StorageLocation

    rows = {r.key: r for r in db.query(StorageLocation).all()}
    out = []
    for key, meta in STORAGE_META.items():
        row = rows.get(key)
        custom = (row.path if row else "") or ""
        resolved = coerce_dir(key, custom)
        out.append(
            {
                "key": key,
                "label": meta["label"],
                "hint": meta["hint"],
                "default_path": str(default_dir(key)),
                "path": custom,
                "resolved_path": str(resolved),
                "writable": _writable(resolved),
            }
        )
    return out


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".wru-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def upsert_location(db, kind: str, path: str) -> dict:
    from .models import StorageLocation

    if kind not in STORAGE_META:
        raise ValueError("Unknown storage location")
    custom = (path or "").strip()
    if custom:
        resolved = coerce_dir(kind, custom)
        if not _writable(resolved):
            raise PermissionError(f"Cannot write to {resolved}")
    row = db.query(StorageLocation).filter(StorageLocation.key == kind).first()
    if row is None:
        row = StorageLocation(key=kind, path=custom)
        db.add(row)
    else:
        row.path = custom
    db.commit()
    return next(item for item in describe_locations(db) if item["key"] == kind)
