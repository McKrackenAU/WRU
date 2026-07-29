from __future__ import annotations

import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import UPLOAD_DIR, get_db
from ..models import DOC_CATEGORIES, Document, Site
from ..schemas import DocumentOut

router = APIRouter(tags=["documents"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


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

    category = (category or "other").strip().lower()
    if category not in DOC_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category. Use one of: {', '.join(DOC_CATEGORIES)}")

    original = Path(file.filename or "upload.bin").name
    suffix = Path(original).suffix[:32]
    # Infer email category from extension when caller left default
    if category == "other" and suffix.lower() in {".eml", ".msg", ".oft"}:
        category = "email"

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
        moa_number=(moa_number or site.moa_number or "").strip() or None,
        category=category,
        description=(description or "").strip() or None,
        stored_name=stored_name,
        original_filename=original,
        content_type=file.content_type,
        size_bytes=size,
        uploaded_by=uploaded_by,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return _doc_out(doc, site)


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
