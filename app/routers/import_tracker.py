"""Upload WRU Traffic TGS-MOA Tracker Excel workbooks.

Off-network imports (Cloudflare Tunnel, workplace file-upload policy) often
block a whole .xlsm because it is a macro-enabled Office file. The chunked
session API sends anonymous 256 KB octet-stream pieces and only assembles the
workbook on the server.
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path
from zipfile import BadZipFile

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..database import DATA_DIR, get_db
from ..tracker_import import import_tracker_rows, parse_tracker_workbook
from ..upload_limits import configure_multipart_limits

configure_multipart_limits()

router = APIRouter(
    prefix="/api/import",
    tags=["import"],
    dependencies=[Depends(require_admin)],
)

MAX_BYTES = 40 * 1024 * 1024
CHUNK_SIZE = 256 * 1024
STAGING_TTL_SEC = 20 * 60
STAGING_DIR = DATA_DIR / "import-staging"
STAGING_DIR.mkdir(parents=True, exist_ok=True)


class TrackerUploadBegin(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(ge=1, le=MAX_BYTES)


def _cleanup_stale_sessions() -> None:
    cutoff = time.time() - STAGING_TTL_SEC
    for path in STAGING_DIR.glob("*"):
        if not path.is_dir():
            continue
        try:
            if path.stat().st_mtime < cutoff:
                shutil.rmtree(path, ignore_errors=True)
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


def _meta_path(folder: Path) -> Path:
    return folder / "meta.json"


def _read_meta(folder: Path) -> dict:
    path = _meta_path(folder)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Upload session expired — start again")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Corrupt upload session") from exc


def _write_meta(folder: Path, meta: dict) -> None:
    _meta_path(folder).write_text(json.dumps(meta), encoding="utf-8")


def _filename_ok(name: str) -> bool:
    lower = (name or "").lower()
    if lower.endswith(".xls") and not lower.endswith((".xlsx", ".xlsm")):
        return False
    return lower.endswith((".xlsx", ".xlsm")) or lower.endswith(".bin")


def _looks_like_workbook(content: bytes) -> bool:
    return len(content) >= 4 and content[:2] == b"PK"


def assemble_chunks(folder: Path, expected_size: int) -> bytes:
    parts = sorted(folder.glob("chunk-*.bin"), key=lambda p: p.name)
    if not parts:
        raise HTTPException(status_code=400, detail="No chunks uploaded")
    buf = bytearray()
    for part in parts:
        buf.extend(part.read_bytes())
        if len(buf) > MAX_BYTES:
            raise HTTPException(status_code=413, detail="File exceeds 40 MB limit")
    if expected_size and len(buf) != expected_size:
        raise HTTPException(
            status_code=400,
            detail=f"Upload incomplete ({len(buf)} of {expected_size} bytes) — retry the import",
        )
    return bytes(buf)


def run_tracker_import(
    db: Session,
    content: bytes,
    *,
    filename: str,
    update_existing: bool,
    dry_run: bool,
) -> dict:
    name = (filename or "").lower()
    if name.endswith(".xls") and not name.endswith((".xlsx", ".xlsm")):
        raise HTTPException(
            status_code=400,
            detail="Legacy .xls is not supported. Save the tracker as .xlsx or .xlsm (Excel → Save As) and retry.",
        )
    if not _filename_ok(name) and not _looks_like_workbook(content):
        raise HTTPException(status_code=400, detail="Upload an Excel .xlsx / .xlsm tracker file")
    if not _looks_like_workbook(content):
        raise HTTPException(
            status_code=400,
            detail="That file is not a valid .xlsx/.xlsm workbook. If it is old .xls, save it as .xlsx first.",
        )
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 40 MB limit")
    try:
        parsed = parse_tracker_workbook(content)
    except BadZipFile as exc:
        raise HTTPException(
            status_code=400,
            detail="That file is not a valid .xlsx/.xlsm workbook. If it is old .xls, save it as .xlsx first.",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not parse workbook: {exc}") from exc
    rows = parsed.get("rows") or []
    if not rows:
        raise HTTPException(
            status_code=400,
            detail="No site rows found. Check you uploaded the TGS-MOA Tracker sheet (Road Name in column B).",
        )
    if dry_run:
        return {
            "dry_run": True,
            "parsed": parsed.get("parsed", len(rows)),
            "sheet_name": parsed.get("sheet_name"),
            "skipped": parsed.get("skipped") or [],
            "unmatched_statuses": parsed.get("unmatched_statuses") or [],
            "sample": [
                {
                    "road_name": r["road_name"],
                    "site_number": r["site_number"],
                    "program": r.get("program"),
                    "status_text": r.get("status_text"),
                    "status_unmatched": r.get("status_unmatched"),
                    "moa_number": r.get("moa_number"),
                    "comments": (r.get("comments") or "")[:160] or None,
                    "councils": r.get("councils") or [],
                }
                for r in rows[:20]
            ],
        }
    result = import_tracker_rows(db, rows, update_existing=update_existing)
    result["dry_run"] = False
    result["sheet_name"] = parsed.get("sheet_name")
    result["unmatched_statuses"] = parsed.get("unmatched_statuses") or []
    return result


@router.post("/tracker")
async def import_tracker_excel(
    file: UploadFile = File(...),
    update_existing: bool = Query(default=True),
    dry_run: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    content = await file.read()
    return run_tracker_import(
        db,
        content,
        filename=file.filename or "tracker.xlsm",
        update_existing=update_existing,
        dry_run=dry_run,
    )


@router.post("/tracker/session")
def begin_tracker_session(payload: TrackerUploadBegin):
    """Start a chunked upload that bypasses .xlsm / whole-file upload filters."""
    _cleanup_stale_sessions()
    if not _filename_ok(payload.filename) and not payload.filename.lower().endswith(".bin"):
        raise HTTPException(status_code=400, detail="Upload an Excel .xlsx / .xlsm tracker file")
    upload_id = str(uuid.uuid4())
    folder = STAGING_DIR / upload_id
    folder.mkdir(parents=True, exist_ok=True)
    chunks = (payload.size + CHUNK_SIZE - 1) // CHUNK_SIZE
    _write_meta(
        folder,
        {
            "filename": Path(payload.filename).name,
            "size": payload.size,
            "chunks": chunks,
            "received": [],
            "created": time.time(),
        },
    )
    return {"id": upload_id, "chunk_size": CHUNK_SIZE, "chunks": chunks}


@router.post("/tracker/session/{upload_id}/chunk/{index}")
async def upload_tracker_chunk(upload_id: str, index: int, request: Request):
    if index < 0 or index > 400:
        raise HTTPException(status_code=400, detail="Invalid chunk index")
    folder = _session_dir(upload_id)
    meta = _read_meta(folder)
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="Empty chunk")
    if len(data) > CHUNK_SIZE + 4096:
        raise HTTPException(status_code=413, detail="Chunk too large")
    received = set(meta.get("received") or [])
    dest = folder / f"chunk-{index:05d}.bin"
    dest.write_bytes(data)
    received.add(index)
    meta["received"] = sorted(received)
    _write_meta(folder, meta)
    return {"received": len(received), "chunks": meta.get("chunks")}


@router.post("/tracker/session/{upload_id}/commit")
def commit_tracker_session(
    upload_id: str,
    update_existing: bool = Query(default=True),
    dry_run: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    folder = _session_dir(upload_id)
    meta = _read_meta(folder)
    expected = int(meta.get("chunks") or 0)
    got = set(meta.get("received") or [])
    if expected and got != set(range(expected)):
        missing = sorted(set(range(expected)) - got)[:8]
        raise HTTPException(
            status_code=400,
            detail=f"Missing chunks {missing} — retry the import",
        )
    try:
        content = assemble_chunks(folder, int(meta.get("size") or 0))
        return run_tracker_import(
            db,
            content,
            filename=str(meta.get("filename") or "tracker.xlsm"),
            update_existing=update_existing,
            dry_run=dry_run,
        )
    finally:
        shutil.rmtree(folder, ignore_errors=True)
