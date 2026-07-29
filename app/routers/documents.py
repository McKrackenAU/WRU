from __future__ import annotations

import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import UPLOAD_DIR, get_db
from ..models import Document, Site
from ..schemas import DocumentOut

router = APIRouter(tags=["documents"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


@router.get("/api/sites/{site_id}/documents", response_model=list[DocumentOut])
def list_documents(site_id: int, db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return (
        db.query(Document)
        .filter(Document.site_id == site_id)
        .order_by(Document.uploaded_at.desc(), Document.id.desc())
        .all()
    )


@router.post("/api/sites/{site_id}/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    site_id: int,
    file: UploadFile = File(...),
    uploaded_by: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    original = Path(file.filename or "upload.bin").name
    suffix = Path(original).suffix[:32]
    stored_name = f"{site_id}_{uuid.uuid4().hex}{suffix}"
    dest = UPLOAD_DIR / stored_name

    size = 0
    async with aiofiles.open(dest, "wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                await out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="File exceeds 25 MB limit")
            await out.write(chunk)

    doc = Document(
        site_id=site_id,
        stored_name=stored_name,
        original_filename=original,
        content_type=file.content_type,
        size_bytes=size,
        uploaded_by=uploaded_by,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.get("/api/documents/{document_id}/download")
def download_document(document_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    path = UPLOAD_DIR / doc.stored_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")

    return FileResponse(
        path,
        media_type=doc.content_type or "application/octet-stream",
        filename=doc.original_filename,
    )


@router.delete("/api/documents/{document_id}", status_code=204)
def delete_document(document_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    path = UPLOAD_DIR / doc.stored_name
    path.unlink(missing_ok=True)
    db.delete(doc)
    db.commit()
    return None
