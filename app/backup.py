"""Pack and restore a full WRU server backup (Postgres dump + uploads + config)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse
from zipfile import ZIP_DEFLATED, ZipFile

from .database import DATA_DIR, build_database_url, engine
from .storage_paths import documents_dir
from .version import version_string

BACKUP_FORMAT = "wru-backup-v1"
DUMP_NAME = "database.dump"
MANIFEST_NAME = "manifest.json"
UPLOADS_PREFIX = "uploads/"
CONFIG_PREFIX = "config/"
CONFIG_FILES = ("nearmap_api_key",)
SKIP_UPLOAD_PARTS = {"doc-staging", "import-staging", "backup-staging"}


def libpq_params() -> dict[str, str]:
    url = os.environ.get("DATABASE_URL") or build_database_url()
    cleaned = url.replace("postgresql+psycopg2://", "postgresql://", 1).replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    parsed = urlparse(cleaned)
    dbname = (parsed.path or "/wru").lstrip("/").split("?")[0] or "wru"
    return {
        "user": unquote(parsed.username or "wru"),
        "password": unquote(parsed.password or ""),
        "host": parsed.hostname or "127.0.0.1",
        "port": str(parsed.port or 5432),
        "dbname": dbname,
    }


def _pg_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PGPASSWORD"] = libpq_params()["password"]
    env.setdefault("PGCONNECT_TIMEOUT", "15")
    return env


def _pg_cmd(binary: str, *extra: str) -> list[str]:
    p = libpq_params()
    return [
        binary,
        "-h",
        p["host"],
        "-p",
        p["port"],
        "-U",
        p["user"],
        *extra,
    ]


def dump_database(dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = _pg_cmd("pg_dump", "-Fc", "--no-owner", "--no-acl", "-d", libpq_params()["dbname"], "-f", str(dest))
    proc = subprocess.run(cmd, env=_pg_env(), capture_output=True, text=True, timeout=900)
    if proc.returncode != 0 or not dest.is_file() or dest.stat().st_size < 32:
        detail = (proc.stderr or proc.stdout or "pg_dump failed").strip()
        raise RuntimeError(detail[:800] or "pg_dump failed")


def restore_database(dump_path: Path) -> str:
    if not dump_path.is_file():
        raise RuntimeError("Backup is missing database.dump")
    engine.dispose()
    cmd = _pg_cmd(
        "pg_restore",
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-acl",
        "-d",
        libpq_params()["dbname"],
        str(dump_path),
    )
    proc = subprocess.run(cmd, env=_pg_env(), capture_output=True, text=True, timeout=900)
    # pg_restore often exits 1 on ignorable "does not exist" notices during --clean.
    if proc.returncode not in {0, 1}:
        detail = (proc.stderr or proc.stdout or "pg_restore failed").strip()
        raise RuntimeError(detail[:800] or "pg_restore failed")
    return (proc.stderr or proc.stdout or "").strip()[-1200:]


def _safe_zip_name(name: str) -> str:
    cleaned = (name or "file").replace("\\", "/").split("/")[-1]
    cleaned = cleaned.replace("\x00", "")
    return cleaned or "file"


def unique_zip_path(used: set[str], relative: str) -> str:
    relative = relative.replace("\\", "/").lstrip("/")
    if relative not in used:
        used.add(relative)
        return relative
    path = Path(relative)
    stem, suffix, parent = path.stem, path.suffix, path.parent.as_posix()
    i = 2
    while True:
        extra = f"{stem} ({i}){suffix}"
        cand = extra if parent in {".", ""} else f"{parent}/{extra}"
        if cand not in used:
            used.add(cand)
            return cand
        i += 1


def iter_upload_files(root: Path | None = None) -> list[Path]:
    base = root or documents_dir()
    if not base.is_dir():
        return []
    out: list[Path] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(base).parts
        if rel_parts and rel_parts[0] in SKIP_UPLOAD_PARTS:
            continue
        out.append(path)
    return out


def build_manifest(*, extra: dict | None = None) -> dict:
    payload = {
        "format": BACKUP_FORMAT,
        "app_version": version_string(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database": {"format": "pg_dump-Fc", "file": DUMP_NAME},
        "uploads": UPLOADS_PREFIX,
        "config_files": [f"{CONFIG_PREFIX}{name}" for name in CONFIG_FILES],
    }
    if extra:
        payload.update(extra)
    return payload


def write_backup_zip(dest: Path) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wru-dump-") as tmp:
        tmp_path = Path(tmp)
        dump_path = tmp_path / DUMP_NAME
        dump_database(dump_path)
        manifest = build_manifest(extra={"upload_files": len(iter_upload_files())})
        with ZipFile(dest, "w", compression=ZIP_DEFLATED, compresslevel=6) as zf:
            zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
            zf.write(dump_path, DUMP_NAME)
            zf.writestr(f"{UPLOADS_PREFIX}.keep", b"")
            for path in iter_upload_files():
                arc = f"{UPLOADS_PREFIX}{path.relative_to(documents_dir()).as_posix()}"
                zf.write(path, arc)
            for name in CONFIG_FILES:
                src = DATA_DIR / name
                if src.is_file():
                    zf.write(src, f"{CONFIG_PREFIX}{name}")
        return manifest


def read_manifest(zf: ZipFile) -> dict:
    try:
        raw = zf.read(MANIFEST_NAME)
    except KeyError as exc:
        raise RuntimeError("Not a WRU backup — missing manifest.json") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Backup manifest is not valid JSON") from exc
    if data.get("format") != BACKUP_FORMAT:
        raise RuntimeError("This file is not a WRU server backup")
    return data


def _extract_member(zf: ZipFile, name: str, dest_dir: Path) -> Path:
    # Prevent zip-slip: keep members under dest_dir.
    target = (dest_dir / name).resolve()
    if not str(target).startswith(str(dest_dir.resolve())):
        raise RuntimeError("Backup contains an unsafe path")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zf.open(name) as src, target.open("wb") as out:
        shutil.copyfileobj(src, out)
    return target


def restore_uploads(extracted_uploads: Path) -> None:
    target = documents_dir()
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    bak = target.parent / f"uploads.bak-{stamp}"
    if any(target.iterdir()):
        shutil.move(str(target), str(bak))
        target.mkdir(parents=True, exist_ok=True)
    else:
        bak = None
    try:
        if extracted_uploads.is_dir():
            for src in extracted_uploads.rglob("*"):
                if not src.is_file():
                    continue
                if src.name == ".keep":
                    continue
                rel = src.relative_to(extracted_uploads)
                dest = target / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
        if bak and bak.exists():
            shutil.rmtree(bak, ignore_errors=True)
    except Exception:
        if bak and bak.exists():
            shutil.rmtree(target, ignore_errors=True)
            shutil.move(str(bak), str(target))
        raise


def restore_config_files(extracted_config: Path) -> None:
    if not extracted_config.is_dir():
        return
    for name in CONFIG_FILES:
        src = extracted_config / name
        if src.is_file():
            dest = DATA_DIR / name
            shutil.copy2(src, dest)


def restore_backup_zip(zip_path: Path) -> dict:
    if not zip_path.is_file():
        raise RuntimeError("Backup file is missing")
    with tempfile.TemporaryDirectory(prefix="wru-restore-") as tmp:
        tmp_path = Path(tmp)
        with ZipFile(zip_path, "r") as zf:
            manifest = read_manifest(zf)
            names = zf.namelist()
            if DUMP_NAME not in names:
                raise RuntimeError("Backup is missing database.dump")
            dump_path = _extract_member(zf, DUMP_NAME, tmp_path)
            for name in names:
                if name.endswith("/"):
                    continue
                if name.startswith(UPLOADS_PREFIX) or name.startswith(CONFIG_PREFIX):
                    _extract_member(zf, name, tmp_path)
        restore_database(dump_path)
        restore_uploads(tmp_path / "uploads")
        restore_config_files(tmp_path / "config")
        from .migrate import run_migrations

        run_migrations()
        return manifest
