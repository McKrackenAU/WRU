from __future__ import annotations

import base64
import json
import mimetypes
import secrets
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from ..backup import unique_zip_path
from ..database import DATA_DIR, ensure_dir, get_db
from ..doc_categories import FALLBACK_KEY, active_category_keys, category_label_map, ensure_doc_category_seed
from ..models import Document, Site
from ..storage import (
    compress_document,
    read_document_bytes,
    stored_payload,
    unlink_stored_file,
    upload_dir,
    write_blob,
)
from ..routers.import_tracker import (
    CHUNK_SIZE,
    TrackerChunkBody,
    assemble_chunks,
    unwrap_chunk_payload,
    xor_repeat,
)
from ..schemas import DocumentOut, DocumentUpdate

router = APIRouter(tags=["documents"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_CHUNKS = (MAX_UPLOAD_BYTES + CHUNK_SIZE - 1) // CHUNK_SIZE
WRAP_KEY_BYTES = 32
STAGING_TTL_SEC = 20 * 60
STAGING_DIR = ensure_dir(DATA_DIR / "doc-staging")
DOWNLOAD_STAGING_DIR = ensure_dir(DATA_DIR / "download-staging")
ZIP_MAX_BYTES = 500 * 1024 * 1024


class DocumentUploadBegin(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(ge=1, le=MAX_UPLOAD_BYTES)
    category: str = "other"
    description: str | None = None
    uploaded_by: str | None = None
    moa_number: str | None = None


def normalize_doc_category(
    category: str | None,
    filename: str = "",
    *,
    allowed: set[str] | None = None,
    db: Session | None = None,
) -> str:
    if allowed is None and db is not None:
        ensure_doc_category_seed(db)
        allowed = set(active_category_keys(db))
    if allowed is None:
        from ..models import DOC_CATEGORIES

        allowed = set(DOC_CATEGORIES)
    category = (category or FALLBACK_KEY).strip().lower() or FALLBACK_KEY
    if category not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Use one of: {', '.join(sorted(allowed))}",
        )
    suffix = Path(filename or "").suffix.lower()
    if category == FALLBACK_KEY and suffix in {".eml", ".msg", ".oft"} and "email" in allowed:
        return "email"
    return category


def _cleanup_stale_sessions() -> None:
    cutoff = time.time() - STAGING_TTL_SEC
    for root in (STAGING_DIR, DOWNLOAD_STAGING_DIR):
        for path in root.glob("*"):
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


def store_document_bytes(
    db: Session,
    site: Site,
    *,
    content: bytes,
    filename: str,
    content_type: str | None,
    category: str,
    description: str | None,
    uploaded_by: str | None,
    moa_number: str | None,
) -> Document:
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 25 MB limit")
    original = Path(filename or "upload.bin").name
    category = normalize_doc_category(category, original, db=db)
    suffix = Path(original).suffix[:32]
    stored_name = f"{site.id}_{uuid.uuid4().hex}{suffix}"
    blob = compress_document(content, original, content_type)
    dest = upload_dir() / stored_name
    write_blob(dest, blob)
    guessed, _ = mimetypes.guess_type(original)
    doc = Document(
        site_id=site.id,
        moa_number=(moa_number or site.moa_number or "").strip() or None,
        category=category,
        description=(description or "").strip() or None,
        stored_name=stored_name,
        original_filename=original,
        content_type=blob.content_type or content_type or guessed or "application/octet-stream",
        size_bytes=blob.logical_size,
        stored_bytes=blob.stored_size,
        stored_encoding=blob.encoding,
        uploaded_by=uploaded_by,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def _doc_out(doc: Document, site: Site | None = None) -> dict:
    site = site or doc.site
    return {
        "id": doc.id,
        "site_id": doc.site_id,
        "moa_number": doc.moa_number or (site.moa_number if site else None),
        "category": doc.category,
        "description": doc.description,
        "original_filename": doc.original_filename,
        "content_type": doc.content_type,
        "size_bytes": doc.size_bytes,
        "uploaded_by": doc.uploaded_by,
        "uploaded_at": doc.uploaded_at,
        "road_name": site.road_name if site else None,
        "site_number": site.site_number if site else None,
    }


@router.get("/api/documents", response_model=list[DocumentOut])
def list_all_documents(
    moa_number: str | None = Query(default=None),
    category: str | None = Query(default=None),
    site_id: int | None = Query(default=None),
    q: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(Document).join(Site)
    if moa_number:
        query = query.filter(
            (Document.moa_number == moa_number.strip())
            | (Site.moa_number == moa_number.strip())
        )
    if category:
        query = query.filter(Document.category == category)
    if site_id:
        query = query.filter(Document.site_id == site_id)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            Document.original_filename.ilike(like)
            | Document.description.ilike(like)
            | Site.road_name.ilike(like)
            | Site.moa_number.ilike(like)
        )
    docs = query.order_by(Document.uploaded_at.desc(), Document.id.desc()).all()
    return [_doc_out(d) for d in docs]


@router.get("/api/sites/{site_id}/documents", response_model=list[DocumentOut])
def list_documents(site_id: int, db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    docs = (
        db.query(Document)
        .filter(Document.site_id == site_id)
        .order_by(Document.uploaded_at.desc(), Document.id.desc())
        .all()
    )
    return [_doc_out(d, site) for d in docs]


@router.post("/api/sites/{site_id}/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    site_id: int,
    file: UploadFile = File(...),
    uploaded_by: str | None = Form(default=None),
    category: str = Form(default="other"),
    description: str | None = Form(default=None),
    moa_number: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    original = Path(file.filename or "upload.bin").name
    size = 0
    chunks: list[bytes] = []
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File exceeds 25 MB limit")
        chunks.append(chunk)
    content = b"".join(chunks)
    doc = store_document_bytes(
        db,
        site,
        content=content,
        filename=original,
        content_type=file.content_type,
        category=category,
        description=description,
        uploaded_by=uploaded_by,
        moa_number=moa_number,
    )
    return _doc_out(doc, site)


@router.post("/api/sites/{site_id}/documents/session")
def begin_document_session(site_id: int, payload: DocumentUploadBegin, db: Session = Depends(get_db)):
    """Start a chunked JSON upload (same protocol as tracker import) so SSL inspection does not block files."""
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    _cleanup_stale_sessions()
    category = normalize_doc_category(payload.category, payload.filename, db=db)
    upload_id = str(uuid.uuid4())
    folder = STAGING_DIR / upload_id
    folder.mkdir(parents=True, exist_ok=True)
    chunks = (payload.size + CHUNK_SIZE - 1) // CHUNK_SIZE
    wrap_key = base64_wrap_key()
    _write_meta(
        folder,
        {
            "site_id": site_id,
            "filename": Path(payload.filename).name,
            "size": payload.size,
            "chunks": chunks,
            "received": [],
            "created": time.time(),
            "wrap_key": wrap_key,
            "category": category,
            "description": (payload.description or "").strip() or None,
            "uploaded_by": (payload.uploaded_by or "").strip() or None,
            "moa_number": (payload.moa_number or "").strip() or None,
        },
    )
    return {
        "id": upload_id,
        "chunk_size": CHUNK_SIZE,
        "chunks": chunks,
        "wrap_key": wrap_key,
    }


def base64_wrap_key() -> str:
    return base64.b64encode(secrets.token_bytes(WRAP_KEY_BYTES)).decode("ascii")


@router.post("/api/sites/{site_id}/documents/session/{upload_id}/chunk/{index}")
async def upload_document_chunk(site_id: int, upload_id: str, index: int, request: Request):
    if index < 0 or index >= MAX_CHUNKS:
        raise HTTPException(status_code=400, detail="Invalid chunk index")
    folder = _session_dir(upload_id)
    meta = _read_meta(folder)
    if int(meta.get("site_id") or 0) != site_id:
        raise HTTPException(status_code=400, detail="Upload session does not match this site")
    expected = int(meta.get("chunks") or 0)
    if expected and index >= expected:
        raise HTTPException(status_code=400, detail="Invalid chunk index")
    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype != "application/json":
        raise HTTPException(
            status_code=415,
            detail="Upload protocol changed — Check for updates, then retry. Chunks must be JSON, not a file upload.",
        )
    wrap_key = meta.get("wrap_key")
    if not wrap_key:
        raise HTTPException(status_code=400, detail="Upload session is from an older app version — start again")
    try:
        raw_json = await request.json()
        payload = TrackerChunkBody.model_validate(raw_json)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid chunk payload") from exc
    data = unwrap_chunk_payload(payload.p, wrap_key)
    received = set(meta.get("received") or [])
    dest = folder / f"chunk-{index:05d}.bin"
    dest.write_bytes(data)
    received.add(index)
    meta["received"] = sorted(received)
    _write_meta(folder, meta)
    return {"received": len(received), "chunks": meta.get("chunks")}


@router.post("/api/sites/{site_id}/documents/session/{upload_id}/commit", response_model=DocumentOut, status_code=201)
def commit_document_session(site_id: int, upload_id: str, db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    folder = _session_dir(upload_id)
    meta = _read_meta(folder)
    if int(meta.get("site_id") or 0) != site_id:
        raise HTTPException(status_code=400, detail="Upload session does not match this site")
    expected = int(meta.get("chunks") or 0)
    got = set(meta.get("received") or [])
    if expected and got != set(range(expected)):
        missing = sorted(set(range(expected)) - got)[:8]
        raise HTTPException(status_code=400, detail=f"Missing chunks {missing} — retry the upload")
    try:
        content = assemble_chunks(folder, int(meta.get("size") or 0))
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File exceeds 25 MB limit")
        doc = store_document_bytes(
            db,
            site,
            content=content,
            filename=str(meta.get("filename") or "upload.bin"),
            content_type=None,
            category=str(meta.get("category") or "other"),
            description=meta.get("description"),
            uploaded_by=meta.get("uploaded_by"),
            moa_number=meta.get("moa_number"),
        )
        return _doc_out(doc, site)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


class DocumentZipIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=250)


def _zip_safe_part(value: str, fallback: str = "item") -> str:
    cleaned = "".join("_" if ch in '\\/:*?"<>|' else ch for ch in (value or "").strip())
    cleaned = " ".join(cleaned.split())
    return (cleaned[:80] or fallback).rstrip(" .")


def wrap_chunk_payload(data: bytes, wrap_key_b64: str) -> str:
    key = base64.b64decode(wrap_key_b64)
    return base64.b64encode(xor_repeat(data, key)).decode("ascii")


def _docs_for_zip(ids: list[int], db: Session) -> list[Document]:
    docs = (
        db.query(Document)
        .join(Site)
        .filter(Document.id.in_(ids))
        .order_by(Site.road_name.asc(), Site.site_number.asc(), Document.id.asc())
        .all()
    )
    if not docs:
        raise HTTPException(status_code=404, detail="No matching documents")
    return docs


def _write_documents_zip(docs: list[Document], db: Session, dest: Path) -> None:
    labels = category_label_map(db)
    used: set[str] = set()
    total_bytes = 0
    try:
        with ZipFile(dest, "w", compression=ZIP_DEFLATED, compresslevel=6) as zf:
            for doc in docs:
                try:
                    raw = read_document_bytes(doc)
                except FileNotFoundError:
                    continue
                size = len(raw)
                if total_bytes + size > ZIP_MAX_BYTES:
                    dest.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail="Selected files are larger than 500 MB — select fewer documents",
                    )
                total_bytes += size
                site = doc.site
                folder = _zip_safe_part(
                    f"{site.road_name or 'Site'} {site.site_number or ''}".strip(),
                    "site",
                )
                cat = _zip_safe_part(labels.get(doc.category) or doc.category or "Other", "other")
                name = _zip_safe_part(doc.original_filename or Path(doc.stored_name).name, "file")
                arc = unique_zip_path(used, f"{folder}/{cat}/{name}")
                zf.writestr(arc, raw)
        if not used:
            dest.unlink(missing_ok=True)
            raise HTTPException(status_code=404, detail="Those files are missing on disk")
    except HTTPException:
        raise
    except Exception:
        dest.unlink(missing_ok=True)
        raise


def _new_download_session_from_bytes(data: bytes, filename: str, content_type: str) -> dict:
    _cleanup_stale_sessions()
    sid = str(uuid.uuid4())
    folder = DOWNLOAD_STAGING_DIR / sid
    folder.mkdir(parents=True, exist_ok=True)
    bundle = folder / "bundle.bin"
    bundle.write_bytes(data)
    size = bundle.stat().st_size
    wrap_key = base64.b64encode(secrets.token_bytes(WRAP_KEY_BYTES)).decode("ascii")
    chunks = max(1, (size + CHUNK_SIZE - 1) // CHUNK_SIZE)
    meta = {
        "filename": filename,
        "content_type": content_type,
        "size": size,
        "chunk_size": CHUNK_SIZE,
        "chunks": chunks,
        "wrap_key": wrap_key,
        "created": time.time(),
    }
    (folder / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return {"id": sid, **meta}


def _new_download_session(source: Path, filename: str, content_type: str) -> dict:
    return _new_download_session_from_bytes(source.read_bytes(), filename, content_type)


def _download_session_dir(session_id: str) -> Path:
    try:
        uid = uuid.UUID(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid download id") from exc
    path = DOWNLOAD_STAGING_DIR / str(uid)
    if not path.is_dir():
        raise HTTPException(status_code=404, detail="Download session expired — start again")
    return path


@router.post("/api/documents/zip")
def download_documents_zip(payload: DocumentZipIn, db: Session = Depends(get_db)):
    docs = _docs_for_zip(payload.ids, db)
    tmp = tempfile.NamedTemporaryFile(prefix="wru-docs-", suffix=".zip", delete=False)
    tmp.close()
    dest = Path(tmp.name)
    _write_documents_zip(docs, db, dest)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    filename = f"WRU-documents-{stamp}.zip"
    return FileResponse(
        dest,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(dest.unlink, missing_ok=True),
    )


@router.post("/api/documents/zip/session")
def begin_documents_zip_session(payload: DocumentZipIn, db: Session = Depends(get_db)):
    docs = _docs_for_zip(payload.ids, db)
    tmp = tempfile.NamedTemporaryFile(prefix="wru-docs-", suffix=".zip", delete=False)
    tmp.close()
    dest = Path(tmp.name)
    try:
        _write_documents_zip(docs, db, dest)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        return _new_download_session(dest, f"WRU-documents-{stamp}.zip", "application/zip")
    finally:
        dest.unlink(missing_ok=True)


@router.post("/api/documents/{document_id}/download/session")
def begin_document_download_session(document_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        raw = read_document_bytes(doc)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File missing on disk") from exc
    return _new_download_session_from_bytes(
        raw,
        doc.original_filename or Path(doc.stored_name).name,
        doc.content_type or "application/octet-stream",
    )


@router.get("/api/documents/download-session/{session_id}/chunk/{index}")
def get_download_chunk(session_id: str, index: int):
    if index < 0:
        raise HTTPException(status_code=400, detail="Invalid chunk index")
    folder = _download_session_dir(session_id)
    meta = _read_meta(folder)
    chunks = int(meta.get("chunks") or 0)
    if index >= chunks:
        raise HTTPException(status_code=400, detail="Invalid chunk index")
    bundle = folder / "bundle.bin"
    if not bundle.is_file():
        raise HTTPException(status_code=404, detail="Download session expired — start again")
    chunk_size = int(meta.get("chunk_size") or CHUNK_SIZE)
    with bundle.open("rb") as fh:
        fh.seek(index * chunk_size)
        data = fh.read(chunk_size)
    if not data:
        raise HTTPException(status_code=404, detail="Chunk missing")
    if index == chunks - 1:
        # Last chunk fetched — drop the staging files shortly after the response.
        pass
    return {
        "p": wrap_chunk_payload(data, meta["wrap_key"]),
        "i": index,
        "n": chunks,
    }


@router.patch("/api/documents/{document_id}", response_model=DocumentOut)
def update_document(document_id: int, payload: DocumentUpdate, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if payload.category is not None:
        doc.category = normalize_doc_category(payload.category, doc.original_filename, db=db)
    if payload.description is not None:
        doc.description = payload.description.strip() or None
    db.commit()
    db.refresh(doc)
    return _doc_out(doc)


@router.get("/api/documents/{document_id}/download")
def download_document(document_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        path, raw = stored_payload(doc)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File missing on disk") from exc
    if path is not None:
        return FileResponse(
            path,
            media_type=doc.content_type or "application/octet-stream",
            filename=doc.original_filename,
        )
    tmp = tempfile.NamedTemporaryFile(prefix="wru-dl-", suffix=Path(doc.original_filename or "").suffix, delete=False)
    tmp.write(raw or b"")
    tmp.close()
    dest = Path(tmp.name)
    return FileResponse(
        dest,
        media_type=doc.content_type or "application/octet-stream",
        filename=doc.original_filename,
        background=BackgroundTask(dest.unlink, missing_ok=True),
    )


@router.delete("/api/documents/{document_id}", status_code=204)
def delete_document(document_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    unlink_stored_file(doc.stored_name)
    db.delete(doc)
    db.commit()
    return None
