"""Admin export / import of a full WRU server backup."""

from __future__ import annotations

import base64
import json
import secrets
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from ..auth import require_admin
from ..backup import restore_backup_zip, write_backup_zip
from ..database import DATA_DIR, ensure_dir
from ..routers.import_tracker import (
    CHUNK_SIZE,
    TrackerChunkBody,
    unwrap_chunk_payload,
)
from ..version import version_string

router = APIRouter(
    prefix="/api/admin/backup",
    tags=["backup"],
    dependencies=[Depends(require_admin)],
)

MAX_BACKUP_BYTES = 2 * 1024 * 1024 * 1024
MAX_CHUNKS = (MAX_BACKUP_BYTES + CHUNK_SIZE - 1) // CHUNK_SIZE
STAGING_TTL_SEC = 60 * 60
STAGING_DIR = DATA_DIR / "backup-staging"


class BackupBegin(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(ge=1, le=MAX_BACKUP_BYTES)


def _cleanup_stale() -> None:
    cutoff = time.time() - STAGING_TTL_SEC
    if not STAGING_DIR.is_dir():
        return
    for path in STAGING_DIR.glob("*"):
        try:
            if path.is_dir() and path.stat().st_mtime < cutoff:
                shutil.rmtree(path, ignore_errors=True)
            elif path.is_file() and path.stat().st_mtime < cutoff and path.suffix == ".zip":
                path.unlink(missing_ok=True)
        except OSError:
            pass


def _session_dir(upload_id: str) -> Path:
    try:
        uid = uuid.UUID(upload_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid upload id") from exc
    path = STAGING_DIR / str(uid)
    if not path.is_dir():
        raise HTTPException(status_code=404, detail="Upload session expired — start again")
    return path


def _read_meta(folder: Path) -> dict:
    path = folder / "meta.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Upload session expired — start again")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Corrupt upload session") from exc


def _write_meta(folder: Path, meta: dict) -> None:
    (folder / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _assemble_to_file(folder: Path, dest: Path, expected_size: int) -> None:
    parts = sorted(folder.glob("chunk-*.bin"), key=lambda p: p.name)
    if not parts:
        raise HTTPException(status_code=400, detail="No chunks uploaded")
    written = 0
    with dest.open("wb") as out:
        for part in parts:
            data = part.read_bytes()
            out.write(data)
            written += len(data)
            if written > MAX_BACKUP_BYTES:
                raise HTTPException(status_code=413, detail="Backup exceeds 2 GB limit")
    if expected_size and written != expected_size:
        raise HTTPException(
            status_code=400,
            detail=f"Upload incomplete ({written} of {expected_size} bytes) — retry the import",
        )


@router.get("/status")
def backup_status():
    return {
        "format": "wru-backup-v1",
        "app_version": version_string(),
        "max_bytes": MAX_BACKUP_BYTES,
        "chunk_size": CHUNK_SIZE,
        "includes": ["PostgreSQL dump", "uploaded files", "config files (Nearmap key if set)"],
    }


@router.get("/export")
def export_backup():
    _cleanup_stale()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"wru-backup-{stamp}.zip"
    ensure_dir(STAGING_DIR)
    dest = STAGING_DIR / filename
    try:
        write_backup_zip(dest)
    except RuntimeError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Could not build backup") from exc
    return FileResponse(
        dest,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(dest.unlink, missing_ok=True),
    )


@router.post("/session")
def begin_backup_session(payload: BackupBegin):
    _cleanup_stale()
    name = Path(payload.filename).name.lower()
    if not name.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Choose a WRU backup .zip file")
    upload_id = str(uuid.uuid4())
    folder = ensure_dir(STAGING_DIR / upload_id)
    wrap_key = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    meta = {
        "filename": Path(payload.filename).name,
        "size": payload.size,
        "chunks": (payload.size + CHUNK_SIZE - 1) // CHUNK_SIZE,
        "received": [],
        "wrap_key": wrap_key,
    }
    if meta["chunks"] > MAX_CHUNKS:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(status_code=413, detail="Backup exceeds 2 GB limit")
    _write_meta(folder, meta)
    return {
        "id": upload_id,
        "chunk_size": CHUNK_SIZE,
        "chunks": meta["chunks"],
        "wrap_key": meta["wrap_key"],
    }


@router.post("/session/{upload_id}/chunk/{index}")
def put_backup_chunk(upload_id: str, index: int, payload: TrackerChunkBody):
    if index < 0 or index >= MAX_CHUNKS:
        raise HTTPException(status_code=400, detail="Invalid chunk index")
    folder = _session_dir(upload_id)
    meta = _read_meta(folder)
    wrap_key = meta.get("wrap_key")
    try:
        data = unwrap_chunk_payload(payload.p, wrap_key)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid chunk payload") from exc
    dest = folder / f"chunk-{index:05d}.bin"
    dest.write_bytes(data)
    received = set(meta.get("received") or [])
    received.add(index)
    meta["received"] = sorted(received)
    _write_meta(folder, meta)
    return {"received": len(received), "chunks": meta.get("chunks")}


@router.post("/session/{upload_id}/commit")
def commit_backup_session(upload_id: str):
    folder = _session_dir(upload_id)
    meta = _read_meta(folder)
    expected = int(meta.get("chunks") or 0)
    got = set(meta.get("received") or [])
    if expected and got != set(range(expected)):
        missing = sorted(set(range(expected)) - got)[:8]
        raise HTTPException(status_code=400, detail=f"Missing chunks {missing} — retry the import")
    assembled = folder / "backup.zip"
    try:
        _assemble_to_file(folder, assembled, int(meta.get("size") or 0))
        manifest = restore_backup_zip(assembled)
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Could not restore backup") from exc
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    from ..live_hub import notify_sites_changed

    notify_sites_changed(reason="backup-restore")
    return {
        "ok": True,
        "message": "Backup restored. Reload the tracker to see the imported data.",
        "manifest": {
            "format": manifest.get("format"),
            "app_version": manifest.get("app_version"),
            "created_at": manifest.get("created_at"),
        },
    }
