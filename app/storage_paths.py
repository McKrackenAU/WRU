"""Resolve configurable file storage roots for future HDD / NAS deploys."""

from __future__ import annotations

import os
from pathlib import Path

from .database import DATA_DIR

MOUNT_ROOTS = ("/mnt", "/media", "/data", "/srv", "/hdd", "/nas", "/opt")
SKIP_FS_TYPES = {
    "proc",
    "sysfs",
    "devtmpfs",
    "devpts",
    "cgroup",
    "cgroup2",
    "tmpfs",
    "overlay",
    "squashfs",
    "autofs",
    "rpc_pipefs",
    "fusectl",
    "fuse.gvfsd-fuse",
    "tracefs",
    "debugfs",
    "securityfs",
    "pstore",
    "bpf",
    "hugetlbfs",
    "mqueue",
    "configfs",
}
SKIP_DIR_NAMES = {".snapshot", "lost+found", "proc", "sys", "dev"}

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


def relative_suffix(kind: str) -> str:
    meta = STORAGE_META.get(kind) or STORAGE_META[DOCUMENTS]
    return str(meta["default_relative"])


def path_on_mount(kind: str, mount: str) -> str:
    root = Path((mount or "").strip() or "/").expanduser()
    if not root.is_absolute():
        root = DATA_DIR / root
    return str(root / relative_suffix(kind))


def infer_mount(kind: str, custom: str | None) -> str | None:
    text = (custom or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    suffix = Path(relative_suffix(kind))
    parts = path.parts
    tail = suffix.parts
    if len(parts) <= len(tail):
        return None
    if parts[-len(tail) :] != tail:
        return None
    root = Path(*parts[: -len(tail)])
    return str(root) if str(root) else "/"


def _is_writable_existing(path: Path) -> bool:
    try:
        return path.is_dir() and os.access(path, os.W_OK | os.X_OK)
    except OSError:
        return False


def _add_mount(found: dict[str, dict], path: Path, *, source: str) -> None:
    try:
        resolved = path.resolve()
    except OSError:
        return
    if not resolved.is_dir() or resolved.name in SKIP_DIR_NAMES:
        return
    key = str(resolved)
    if key in {"/", "/boot", "/boot/efi", "/proc", "/sys", "/dev", "/run"}:
        return
    if key not in found:
        found[key] = {
            "path": key,
            "label": key,
            "writable": _is_writable_existing(resolved),
            "source": source,
        }


def list_candidate_mounts() -> list[dict]:
    """Disks / folders an admin can pick so the app can create the rest of the path."""
    found: dict[str, dict] = {}
    for raw in MOUNT_ROOTS:
        root = Path(raw)
        if not root.is_dir():
            continue
        _add_mount(found, root, source="root")
        try:
            children = sorted(root.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            children = []
        for child in children:
            if child.is_dir() and not child.is_symlink():
                _add_mount(found, child, source="child")

    mounts_file = Path("/proc/mounts")
    if mounts_file.is_file():
        try:
            lines = mounts_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            lines = []
        for line in lines:
            bits = line.split()
            if len(bits) < 3:
                continue
            mp, fstype = bits[1], bits[2]
            if fstype in SKIP_FS_TYPES:
                continue
            point = Path(mp)
            if any(str(point) == root or str(point).startswith(f"{root}/") for root in MOUNT_ROOTS):
                _add_mount(found, point, source="mount")

    data = Path(DATA_DIR)
    _add_mount(found, data, source="app")

    rows = list(found.values())
    rows.sort(key=lambda row: (0 if row["path"] == str(Path(DATA_DIR).resolve()) else 1, row["path"]))
    for row in rows:
        if row["path"] == str(Path(DATA_DIR).resolve()):
            row["label"] = f"{row['path']} (app data)"
    return rows


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
                "default_relative": meta["default_relative"],
                "path": custom,
                "resolved_path": str(resolved),
                "writable": _writable(resolved),
                "inferred_mount": infer_mount(key, custom),
            }
        )
    return out


def describe_storage(db) -> dict:
    return {"locations": describe_locations(db), "mounts": list_candidate_mounts()}


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".wru-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def allowed_mount(mount: str) -> bool:
    raw = (mount or "").strip()
    if not raw:
        return False
    try:
        want = str(Path(raw).expanduser().resolve())
    except OSError:
        return False
    return any(item["path"] == want for item in list_candidate_mounts())


def upsert_location(db, kind: str, path: str, *, mount: str | None = None) -> dict:
    from .models import StorageLocation

    if kind not in STORAGE_META:
        raise ValueError("Unknown storage location")
    custom = (path or "").strip()
    if mount:
        if not allowed_mount(mount):
            raise ValueError("That disk / mount is not available on this server")
        custom = path_on_mount(kind, mount)
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
