"""Comms planner — sheets, columns, rows, and notification documents."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_comms
from ..comms_export import build_comms_pdf, build_comms_xlsx, collect_export_tables
from ..comms_links import normalize_resource_url
from ..comms_seed import ensure_comms_resources, ensure_comms_seed
from ..database import get_db
from ..live_hub import notify_from_request
from ..models import (
    CommsColumn,
    CommsResourceLink,
    CommsResourceSection,
    CommsRow,
    CommsRowNote,
    CommsSheet,
    CommsTemplateField,
    Document,
    ProgramCategory,
    Site,
    User,
)
from ..routers.documents import (
    DocumentUploadBegin,
    _doc_out,
    _read_meta,
    _session_dir,
    _write_meta,
    assemble_chunks,
    base64_wrap_key,
    normalize_doc_category,
    store_document_bytes,
)
from ..routers.import_tracker import CHUNK_SIZE, TrackerChunkBody, unwrap_chunk_payload
from ..services import slugify_field_key

router = APIRouter(prefix="/api/comms", tags=["comms"], dependencies=[Depends(require_comms)])

FIELD_TYPES = {"text", "number", "date", "checkbox", "select"}
FORM_FIELD_TYPES = {"yesno", "select", "text", "textarea", "file"}
VISIBILITY = {"users", "comms"}
SCOPING_CATEGORY = "scoping"


class SheetCreate(BaseModel):
    title: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=255)


class SheetUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=255)
    position: int | None = None
    settings: dict | None = None


class ColumnCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    field_type: str = "text"
    options: list[str] | None = None
    created_by: str | None = None
    apply_all: bool = False


class ColumnUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    field_type: str | None = None
    options: list[str] | None = None
    position: int | None = None


class RowCreate(BaseModel):
    values: dict = Field(default_factory=dict)
    section: str | None = Field(default=None, max_length=255)
    site_id: int | None = None
    created_by: str | None = None


class RowUpdate(BaseModel):
    values: dict | None = None
    form_values: dict | None = None
    section: str | None = Field(default=None, max_length=255)
    site_id: int | None = None
    clear_site: bool = False


class NoteCreate(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    created_by: str | None = None


class FormFieldCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    field_type: str = "yesno"
    options: list[str] | None = None
    created_by: str | None = None


class FormFieldUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    field_type: str | None = None
    options: list[str] | None = None
    position: int | None = None


class ReorderIn(BaseModel):
    ids: list[int] = Field(min_length=1)


class ResourceSectionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=128)
    body: str | None = Field(default=None, max_length=8000)
    created_by: str | None = None


class ResourceSectionUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=128)
    body: str | None = Field(default=None, max_length=8000)
    position: int | None = None


class CommsExportIn(BaseModel):
    format: str = "xlsx"
    sheet_ids: list[int] = Field(default_factory=list)
    column_keys: list[str] = Field(default_factory=list)
    row_ids: list[int] | None = None
    include_job: bool = True


class ResourceLinkCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=2000)
    note: str | None = Field(default=None, max_length=500)
    created_by: str | None = None


class ResourceLinkUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=500)
    position: int | None = None


def _sheet_or_404(db: Session, sheet_id: int) -> CommsSheet:
    ensure_comms_seed(db)
    sheet = db.get(CommsSheet, sheet_id)
    if not sheet:
        raise HTTPException(status_code=404, detail="Sheet not found")
    return sheet


def _row_or_404(db: Session, row_id: int) -> CommsRow:
    row = db.get(CommsRow, row_id)
    if not row:
        raise HTTPException(status_code=404, detail="Row not found")
    return row


def _column_or_404(db: Session, column_id: int) -> CommsColumn:
    col = db.get(CommsColumn, column_id)
    if not col:
        raise HTTPException(status_code=404, detail="Column not found")
    return col


def _unique_sheet_key(db: Session, title: str) -> str:
    base = slugify_field_key(title)
    key = base
    suffix = 2
    while db.query(CommsSheet).filter(CommsSheet.key == key).first():
        key = f"{base}_{suffix}"
        suffix += 1
    return key


def _unique_field_key(db: Session, sheet_id: int, name: str) -> str:
    base = slugify_field_key(name)
    key = base
    suffix = 2
    while (
        db.query(CommsColumn)
        .filter(CommsColumn.sheet_id == sheet_id, CommsColumn.field_key == key)
        .first()
    ):
        key = f"{base}_{suffix}"
        suffix += 1
    return key


def _site_brief(site: Site | None) -> dict | None:
    if not site:
        return None
    return {
        "id": site.id,
        "road_name": site.road_name,
        "site_number": site.site_number,
        "program": site.program,
        "moa_number": site.moa_number,
        "archived": bool(site.archived),
    }


def _column_out(col: CommsColumn) -> dict:
    return {
        "id": col.id,
        "sheet_id": col.sheet_id,
        "name": col.name,
        "field_key": col.field_key,
        "field_type": col.field_type,
        "options": col.options,
        "position": col.position,
        "created_by": col.created_by,
        "created_at": col.created_at,
    }


def _row_out(row: CommsRow, *, include_docs: bool = False) -> dict:
    docs = []
    if include_docs:
        docs = [_doc_out(d, row.site) for d in sorted(row.documents, key=lambda d: d.id, reverse=True)]
    return {
        "id": row.id,
        "sheet_id": row.sheet_id,
        "position": row.position,
        "section": row.section,
        "values": row.values or {},
        "form_values": row.form_values or {},
        "note_count": len(row.notes or []),
        "site_id": row.site_id,
        "site": _site_brief(row.site),
        "document_count": len(row.documents or []),
        "documents": docs,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _sheet_out(sheet: CommsSheet, *, with_rows: bool = False) -> dict:
    columns = sorted(sheet.columns, key=lambda c: (c.position, c.id))
    payload = {
        "id": sheet.id,
        "key": sheet.key,
        "title": sheet.title,
        "description": sheet.description,
        "position": sheet.position,
        "seeded": bool(sheet.seeded),
        "settings": sheet.settings or {},
        "column_count": len(columns),
        "row_count": len(sheet.rows or []),
        "columns": [_column_out(c) for c in columns],
    }
    if with_rows:
        rows = sorted(sheet.rows, key=lambda r: (r.position, r.id))
        payload["rows"] = [_row_out(r) for r in rows]
    return payload


def _sync_row_documents_site(row: CommsRow) -> None:
    for doc in row.documents or []:
        doc.site_id = row.site_id
        if row.site is not None:
            doc.moa_number = row.site.moa_number or doc.moa_number


@router.get("/sheets")
def list_sheets(db: Session = Depends(get_db)):
    ensure_comms_seed(db)
    sheets = db.query(CommsSheet).order_by(CommsSheet.position.asc(), CommsSheet.id.asc()).all()
    return [_sheet_out(s) for s in sheets]


@router.post("/sheets", status_code=201)
def create_sheet(payload: SheetCreate, request: Request, db: Session = Depends(get_db)):
    ensure_comms_seed(db)
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Sheet title is required")
    max_pos = db.query(func.max(CommsSheet.position)).scalar()
    sheet = CommsSheet(
        key=_unique_sheet_key(db, title),
        title=title,
        description=(payload.description or "").strip() or None,
        position=(max_pos or 0) + 1,
        seeded=False,
    )
    db.add(sheet)
    db.commit()
    db.refresh(sheet)
    notify_from_request(request, reason="comms_sheet")
    return _sheet_out(sheet, with_rows=True)


@router.get("/sheets/{sheet_id}")
def get_sheet(sheet_id: int, db: Session = Depends(get_db)):
    return _sheet_out(_sheet_or_404(db, sheet_id), with_rows=True)


@router.patch("/sheets/{sheet_id}")
def update_sheet(sheet_id: int, payload: SheetUpdate, request: Request, db: Session = Depends(get_db)):
    sheet = _sheet_or_404(db, sheet_id)
    if payload.title is not None:
        title = payload.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="Sheet title is required")
        sheet.title = title
    if payload.description is not None:
        sheet.description = payload.description.strip() or None
    if payload.position is not None:
        sheet.position = payload.position
    if payload.settings is not None:
        current = dict(sheet.settings or {})
        incoming = payload.settings
        if "colors" in incoming and isinstance(incoming.get("colors"), dict):
            colors = {}
            for key, value in incoming["colors"].items():
                name = str(key).strip()[:255]
                if not name or value in (None, ""):
                    continue
                colors[name] = str(value).strip()[:32]
            current["colors"] = colors
        sheet.settings = current
    db.commit()
    db.refresh(sheet)
    notify_from_request(request, reason="comms_sheet")
    return _sheet_out(sheet)


@router.delete("/sheets/{sheet_id}", status_code=204)
def delete_sheet(sheet_id: int, request: Request, db: Session = Depends(get_db)):
    sheet = _sheet_or_404(db, sheet_id)
    db.delete(sheet)
    db.commit()
    notify_from_request(request, reason="comms_sheet")
    return None


def _section_or_404(db: Session, section_id: int) -> CommsResourceSection:
    section = db.get(CommsResourceSection, section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Heading not found")
    return section


def _link_or_404(db: Session, link_id: int) -> CommsResourceLink:
    link = db.get(CommsResourceLink, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    return link


def _link_out(link: CommsResourceLink) -> dict:
    return {
        "id": link.id,
        "section_id": link.section_id,
        "title": link.title,
        "url": link.url,
        "note": link.note,
        "position": link.position,
        "created_by": link.created_by,
        "created_at": link.created_at,
        "updated_at": link.updated_at,
    }


def _section_out(section: CommsResourceSection) -> dict:
    links = sorted(section.links or [], key=lambda item: (item.position, item.id))
    return {
        "id": section.id,
        "title": section.title,
        "body": section.body or "",
        "position": section.position,
        "created_by": section.created_by,
        "created_at": section.created_at,
        "links": [_link_out(link) for link in links],
    }


def _safe_url(raw: str) -> str:
    try:
        return normalize_resource_url(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/resources")
def list_resources(db: Session = Depends(get_db)):
    ensure_comms_resources(db)
    sections = (
        db.query(CommsResourceSection)
        .order_by(CommsResourceSection.position.asc(), CommsResourceSection.id.asc())
        .all()
    )
    return {"sections": [_section_out(section) for section in sections]}


@router.post("/resources/sections", status_code=201)
def create_resource_section(payload: ResourceSectionCreate, request: Request, db: Session = Depends(get_db)):
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Heading is required")
    max_pos = db.query(func.max(CommsResourceSection.position)).scalar()
    section = CommsResourceSection(
        title=title[:128],
        body=(payload.body or "").strip()[:8000] or None,
        position=(max_pos or 0) + 1,
        created_by=payload.created_by,
    )
    db.add(section)
    db.commit()
    db.refresh(section)
    notify_from_request(request, reason="comms_resources")
    return _section_out(section)


@router.patch("/resources/sections/{section_id}")
def update_resource_section(
    section_id: int, payload: ResourceSectionUpdate, request: Request, db: Session = Depends(get_db)
):
    section = _section_or_404(db, section_id)
    if payload.title is not None:
        title = payload.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="Heading is required")
        section.title = title[:128]
    if payload.body is not None:
        section.body = payload.body.strip()[:8000] or None
    if payload.position is not None:
        section.position = payload.position
    db.commit()
    db.refresh(section)
    notify_from_request(request, reason="comms_resources")
    return _section_out(section)


@router.delete("/resources/sections/{section_id}", status_code=204)
def delete_resource_section(section_id: int, request: Request, db: Session = Depends(get_db)):
    section = _section_or_404(db, section_id)
    db.delete(section)
    db.commit()
    notify_from_request(request, reason="comms_resources")
    return None


@router.post("/resources/sections/{section_id}/links", status_code=201)
def create_resource_link(
    section_id: int, payload: ResourceLinkCreate, request: Request, db: Session = Depends(get_db)
):
    section = _section_or_404(db, section_id)
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Link name is required")
    max_pos = (
        db.query(func.max(CommsResourceLink.position))
        .filter(CommsResourceLink.section_id == section.id)
        .scalar()
    )
    link = CommsResourceLink(
        section_id=section.id,
        title=title[:200],
        url=_safe_url(payload.url),
        note=(payload.note or "").strip()[:500] or None,
        position=(max_pos or 0) + 1,
        created_by=payload.created_by,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    notify_from_request(request, reason="comms_resources")
    return _link_out(link)


@router.patch("/resources/links/{link_id}")
def update_resource_link(link_id: int, payload: ResourceLinkUpdate, request: Request, db: Session = Depends(get_db)):
    link = _link_or_404(db, link_id)
    if payload.title is not None:
        title = payload.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="Link name is required")
        link.title = title[:200]
    if payload.url is not None:
        link.url = _safe_url(payload.url)
    if payload.note is not None:
        link.note = payload.note.strip()[:500] or None
    if payload.position is not None:
        link.position = payload.position
    db.commit()
    db.refresh(link)
    notify_from_request(request, reason="comms_resources")
    return _link_out(link)


@router.delete("/resources/links/{link_id}", status_code=204)
def delete_resource_link(link_id: int, request: Request, db: Session = Depends(get_db)):
    link = _link_or_404(db, link_id)
    db.delete(link)
    db.commit()
    notify_from_request(request, reason="comms_resources")
    return None


@router.post("/export")
def export_comms(payload: CommsExportIn, db: Session = Depends(get_db)):
    fmt = (payload.format or "xlsx").lower().strip()
    if fmt not in {"xlsx", "pdf"}:
        raise HTTPException(status_code=400, detail="Choose Excel or PDF")
    query = db.query(CommsSheet)
    if payload.sheet_ids:
        query = query.filter(CommsSheet.id.in_(payload.sheet_ids))
    sheets = query.order_by(CommsSheet.position.asc(), CommsSheet.id.asc()).all()
    if not sheets:
        raise HTTPException(status_code=400, detail="Select at least one planner tab")
    packed = [_sheet_out(sheet, with_rows=True) for sheet in sheets]
    tables = collect_export_tables(
        packed,
        column_keys=payload.column_keys or [],
        row_ids=payload.row_ids,
        include_job=payload.include_job,
    )
    title = "WRU comms planner" if len(sheets) > 1 else f"WRU comms — {sheets[0].title}"
    if fmt == "pdf":
        data = build_comms_pdf(tables, title=title)
        media = "application/pdf"
        ext = "pdf"
    else:
        data = build_comms_xlsx(tables, title=title)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ext = "xlsx"
    slug = "comms-planner" if len(sheets) > 1 else slugify_field_key(sheets[0].title)
    filename = f"{slug}-{date.today().isoformat()}.{ext}"
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/sheets/{sheet_id}/columns", status_code=201)
def create_column(sheet_id: int, payload: ColumnCreate, request: Request, db: Session = Depends(get_db)):
    sheet = _sheet_or_404(db, sheet_id)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Column name is required")
    ftype = payload.field_type if payload.field_type in FIELD_TYPES else "text"
    max_pos = (
        db.query(func.max(CommsColumn.position)).filter(CommsColumn.sheet_id == sheet.id).scalar()
    )
    col = CommsColumn(
        sheet_id=sheet.id,
        name=name,
        field_key=_unique_field_key(db, sheet.id, name),
        field_type=ftype,
        options=payload.options if ftype == "select" else None,
        position=(max_pos or 0) + 1,
        created_by=payload.created_by,
    )
    db.add(col)
    created = [col]
    if payload.apply_all:
        others = db.query(CommsSheet).filter(CommsSheet.id != sheet.id).all()
        for other in others:
            exists = (
                db.query(CommsColumn)
                .filter(CommsColumn.sheet_id == other.id, CommsColumn.field_key == col.field_key)
                .first()
            )
            if exists:
                continue
            max_other = (
                db.query(func.max(CommsColumn.position)).filter(CommsColumn.sheet_id == other.id).scalar()
            )
            extra = CommsColumn(
                sheet_id=other.id,
                name=name,
                field_key=_unique_field_key(db, other.id, name),
                field_type=ftype,
                options=payload.options if ftype == "select" else None,
                position=(max_other or 0) + 1,
                created_by=payload.created_by,
            )
            db.add(extra)
            created.append(extra)
    db.commit()
    db.refresh(col)
    notify_from_request(request, reason="comms_column")
    return _column_out(col)


@router.patch("/columns/{column_id}")
def update_column(column_id: int, payload: ColumnUpdate, request: Request, db: Session = Depends(get_db)):
    col = _column_or_404(db, column_id)
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Column name is required")
        col.name = name
    if payload.field_type is not None:
        if payload.field_type not in FIELD_TYPES:
            raise HTTPException(status_code=400, detail="Invalid column type")
        col.field_type = payload.field_type
        if col.field_type != "select":
            col.options = None
    if payload.options is not None and col.field_type == "select":
        col.options = payload.options
    if payload.position is not None:
        col.position = payload.position
    db.commit()
    db.refresh(col)
    notify_from_request(request, reason="comms_column")
    return _column_out(col)


@router.delete("/columns/{column_id}", status_code=204)
def delete_column(column_id: int, request: Request, db: Session = Depends(get_db)):
    col = _column_or_404(db, column_id)
    field_key = col.field_key
    sheet_id = col.sheet_id
    rows = db.query(CommsRow).filter(CommsRow.sheet_id == sheet_id).all()
    for row in rows:
        fields = dict(row.values or {})
        if field_key in fields:
            fields.pop(field_key, None)
            row.values = fields
    db.delete(col)
    db.commit()
    notify_from_request(request, reason="comms_column")
    return None


@router.post("/sheets/{sheet_id}/columns/reorder")
def reorder_columns(sheet_id: int, payload: ReorderIn, request: Request, db: Session = Depends(get_db)):
    sheet = _sheet_or_404(db, sheet_id)
    by_id = {c.id: c for c in sheet.columns}
    if set(payload.ids) != set(by_id):
        raise HTTPException(status_code=400, detail="Reorder list must include every column")
    for pos, cid in enumerate(payload.ids):
        by_id[cid].position = pos
    db.commit()
    notify_from_request(request, reason="comms_column")
    return [_column_out(by_id[cid]) for cid in payload.ids]


@router.post("/sheets/{sheet_id}/rows", status_code=201)
def create_row(sheet_id: int, payload: RowCreate, request: Request, db: Session = Depends(get_db)):
    sheet = _sheet_or_404(db, sheet_id)
    site = None
    if payload.site_id is not None:
        site = db.get(Site, payload.site_id)
        if not site:
            raise HTTPException(status_code=404, detail="Site not found")
    max_pos = db.query(func.max(CommsRow.position)).filter(CommsRow.sheet_id == sheet.id).scalar()
    row = CommsRow(
        sheet_id=sheet.id,
        position=(max_pos or 0) + 1,
        section=(payload.section or "").strip() or None,
        values=payload.values or {},
        site_id=site.id if site else None,
        created_by=payload.created_by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    notify_from_request(request, site_ids=[row.site_id] if row.site_id else None, reason="comms_row")
    return _row_out(row, include_docs=True)


@router.patch("/rows/{row_id}")
def update_row(row_id: int, payload: RowUpdate, request: Request, db: Session = Depends(get_db)):
    row = _row_or_404(db, row_id)
    if payload.values is not None:
        merged = dict(row.values or {})
        merged.update(payload.values)
        row.values = merged
    if payload.form_values is not None:
        merged_form = dict(row.form_values or {})
        merged_form.update(payload.form_values)
        row.form_values = merged_form
    if payload.section is not None:
        row.section = payload.section.strip() or None
    if payload.clear_site:
        row.site_id = None
    elif payload.site_id is not None:
        site = db.get(Site, payload.site_id)
        if not site:
            raise HTTPException(status_code=404, detail="Site not found")
        row.site_id = site.id
    _sync_row_documents_site(row)
    db.commit()
    db.refresh(row)
    notify_from_request(request, site_ids=[row.site_id] if row.site_id else None, reason="comms_row")
    return _row_out(row, include_docs=True)


@router.delete("/rows/{row_id}", status_code=204)
def delete_row(row_id: int, request: Request, db: Session = Depends(get_db)):
    row = _row_or_404(db, row_id)
    site_id = row.site_id
    db.delete(row)
    db.commit()
    notify_from_request(request, site_ids=[site_id] if site_id else None, reason="comms_row")
    return None


@router.get("/sites")
def lookup_sites(
    q: str | None = Query(default=None),
    program: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(Site).filter(Site.archived.is_(False))
    if program == "(Unassigned)":
        query = query.filter((Site.program.is_(None)) | (Site.program == ""))
    elif program and program.strip():
        query = query.filter(func.lower(Site.program) == program.strip().lower())
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            (Site.road_name.ilike(like))
            | (Site.site_number.ilike(like))
            | (Site.moa_number.ilike(like))
            | (Site.program.ilike(like))
        )
    limit = 400 if program else 80
    rows = query.order_by(Site.road_name.asc(), Site.site_number.asc()).limit(limit).all()
    return [_site_brief(s) for s in rows]


@router.get("/site-categories")
def list_site_categories(db: Session = Depends(get_db)):
    named = [
        r[0]
        for r in db.query(ProgramCategory.name)
        .filter(ProgramCategory.active.is_(True))
        .order_by(ProgramCategory.position.asc(), ProgramCategory.name.asc())
        .all()
    ]
    used = {
        (row[0] or "").strip()
        for row in db.query(Site.program).filter(Site.archived.is_(False)).distinct().all()
    }
    used.discard("")
    labels = []
    seen = set()
    for name in named + sorted(used, key=str.lower):
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        labels.append(name)
    if (
        db.query(Site)
        .filter(Site.archived.is_(False), (Site.program.is_(None)) | (Site.program == ""))
        .first()
    ):
        labels.append("(Unassigned)")
    return [{"name": name} for name in labels]


def _note_out(note: CommsRowNote) -> dict:
    return {
        "id": note.id,
        "row_id": note.row_id,
        "message": note.message,
        "created_by": note.created_by,
        "created_at": note.created_at,
    }


def _form_field_out(field: CommsTemplateField) -> dict:
    return {
        "id": field.id,
        "name": field.name,
        "field_key": field.field_key,
        "field_type": field.field_type,
        "options": field.options,
        "position": field.position,
        "created_by": field.created_by,
        "created_at": field.created_at,
    }


def _unique_form_key(db: Session, name: str) -> str:
    base = slugify_field_key(name)
    key = base
    suffix = 2
    while db.query(CommsTemplateField).filter(CommsTemplateField.field_key == key).first():
        key = f"{base}_{suffix}"
        suffix += 1
    return key


@router.get("/rows/{row_id}/notes")
def list_row_notes(row_id: int, db: Session = Depends(get_db)):
    row = _row_or_404(db, row_id)
    notes = sorted(row.notes or [], key=lambda n: (n.created_at, n.id), reverse=True)
    return [_note_out(n) for n in notes]


@router.post("/rows/{row_id}/notes", status_code=201)
def create_row_note(row_id: int, payload: NoteCreate, request: Request, db: Session = Depends(get_db)):
    row = _row_or_404(db, row_id)
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Note is required")
    note = CommsRowNote(row_id=row.id, message=message[:4000], created_by=payload.created_by)
    db.add(note)
    db.commit()
    db.refresh(note)
    notify_from_request(request, site_ids=[row.site_id] if row.site_id else None, reason="comms_note")
    return _note_out(note)


@router.delete("/notes/{note_id}", status_code=204)
def delete_row_note(note_id: int, request: Request, db: Session = Depends(get_db)):
    note = db.get(CommsRowNote, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    site_id = note.row.site_id if note.row else None
    db.delete(note)
    db.commit()
    notify_from_request(request, site_ids=[site_id] if site_id else None, reason="comms_note")
    return None


@router.get("/form-fields")
def list_form_fields(db: Session = Depends(get_db)):
    rows = db.query(CommsTemplateField).order_by(CommsTemplateField.position.asc(), CommsTemplateField.id.asc()).all()
    return [_form_field_out(f) for f in rows]


@router.post("/form-fields", status_code=201)
def create_form_field(payload: FormFieldCreate, request: Request, db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Field name is required")
    ftype = payload.field_type if payload.field_type in FORM_FIELD_TYPES else "yesno"
    options = payload.options if ftype == "select" else (["Yes", "No"] if ftype == "yesno" else None)
    if ftype == "select":
        options = [str(o).strip() for o in (payload.options or []) if str(o).strip()]
        if not options:
            raise HTTPException(status_code=400, detail="Select fields need at least one option")
    max_pos = db.query(func.max(CommsTemplateField.position)).scalar()
    field = CommsTemplateField(
        name=name[:128],
        field_key=_unique_form_key(db, name),
        field_type=ftype,
        options=options,
        position=(max_pos or 0) + 1,
        created_by=payload.created_by,
    )
    db.add(field)
    db.commit()
    db.refresh(field)
    notify_from_request(request, reason="comms_form_field")
    return _form_field_out(field)


@router.patch("/form-fields/{field_id}")
def update_form_field(field_id: int, payload: FormFieldUpdate, request: Request, db: Session = Depends(get_db)):
    field = db.get(CommsTemplateField, field_id)
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Field name is required")
        field.name = name[:128]
    if payload.field_type is not None:
        if payload.field_type not in FORM_FIELD_TYPES:
            raise HTTPException(status_code=400, detail="Invalid field type")
        field.field_type = payload.field_type
        if payload.field_type == "yesno":
            field.options = ["Yes", "No"]
        elif payload.field_type != "select":
            field.options = None
    if payload.options is not None and field.field_type == "select":
        field.options = [str(o).strip() for o in payload.options if str(o).strip()]
    if payload.position is not None:
        field.position = payload.position
    db.commit()
    db.refresh(field)
    notify_from_request(request, reason="comms_form_field")
    return _form_field_out(field)


@router.delete("/form-fields/{field_id}", status_code=204)
def delete_form_field(field_id: int, request: Request, db: Session = Depends(get_db)):
    field = db.get(CommsTemplateField, field_id)
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")
    db.delete(field)
    db.commit()
    notify_from_request(request, reason="comms_form_field")
    return None


@router.get("/rows/{row_id}/documents")
def list_row_documents(row_id: int, db: Session = Depends(get_db)):
    row = _row_or_404(db, row_id)
    docs = (
        db.query(Document)
        .filter(Document.comms_row_id == row.id)
        .order_by(Document.uploaded_at.desc(), Document.id.desc())
        .all()
    )
    return [_doc_out(d, row.site) for d in docs]


class CommsDocBegin(DocumentUploadBegin):
    visibility: str = "comms"


def _normalize_visibility(value: str | None) -> str:
    vis = (value or "comms").strip().lower()
    if vis not in VISIBILITY:
        raise HTTPException(status_code=400, detail="Visibility must be users or comms")
    return vis


@router.post("/rows/{row_id}/documents", status_code=201)
async def upload_row_document(
    row_id: int,
    request: Request,
    file: UploadFile = File(...),
    uploaded_by: str | None = Form(default=None),
    category: str = Form(default="other"),
    description: str | None = Form(default=None),
    visibility: str = Form(default="comms"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = _row_or_404(db, row_id)
    vis = _normalize_visibility(visibility)
    original = Path(file.filename or "upload.bin").name
    chunks: list[bytes] = []
    size = 0
    from ..routers.documents import MAX_UPLOAD_BYTES

    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File exceeds 25 MB limit")
        chunks.append(chunk)
    content = b"".join(chunks)
    site = row.site
    doc = store_document_bytes(
        db,
        site,
        content=content,
        filename=original,
        content_type=file.content_type,
        category=category,
        description=description,
        uploaded_by=uploaded_by or user.display_name or user.username,
        moa_number=site.moa_number if site else None,
        visibility=vis,
        source="comms",
        comms_row_id=row.id,
        allow_missing_site=True,
    )
    notify_from_request(request, site_ids=[row.site_id] if row.site_id else None, reason="comms_doc")
    return _doc_out(doc, site)


@router.post("/rows/{row_id}/documents/session")
def begin_row_document_session(
    row_id: int,
    payload: CommsDocBegin,
    db: Session = Depends(get_db),
):
    from ..routers.documents import STAGING_DIR, _cleanup_stale_sessions
    import time
    import uuid

    row = _row_or_404(db, row_id)
    _cleanup_stale_sessions()
    category = normalize_doc_category(payload.category, payload.filename, db=db)
    vis = _normalize_visibility(payload.visibility)
    upload_id = str(uuid.uuid4())
    folder = STAGING_DIR / upload_id
    folder.mkdir(parents=True, exist_ok=True)
    chunks = (payload.size + CHUNK_SIZE - 1) // CHUNK_SIZE
    wrap_key = base64_wrap_key()
    _write_meta(
        folder,
        {
            "comms_row_id": row.id,
            "site_id": row.site_id,
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
            "visibility": vis,
            "source": "comms",
        },
    )
    return {
        "id": upload_id,
        "chunk_size": CHUNK_SIZE,
        "chunks": chunks,
        "wrap_key": wrap_key,
    }


@router.post("/rows/{row_id}/documents/session/{upload_id}/chunk/{index}")
async def upload_row_document_chunk(row_id: int, upload_id: str, index: int, request: Request):
    from ..routers.documents import MAX_CHUNKS

    folder = _session_dir(upload_id)
    meta = _read_meta(folder)
    if int(meta.get("comms_row_id") or 0) != row_id:
        raise HTTPException(status_code=400, detail="Upload session does not match this row")
    if index < 0 or index >= MAX_CHUNKS:
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


@router.post("/rows/{row_id}/documents/session/{upload_id}/commit", status_code=201)
def commit_row_document_session(
    row_id: int,
    upload_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    import shutil

    from ..routers.documents import MAX_UPLOAD_BYTES

    row = _row_or_404(db, row_id)
    folder = _session_dir(upload_id)
    meta = _read_meta(folder)
    if int(meta.get("comms_row_id") or 0) != row_id:
        raise HTTPException(status_code=400, detail="Upload session does not match this row")
    expected = int(meta.get("chunks") or 0)
    got = set(meta.get("received") or [])
    if expected and got != set(range(expected)):
        missing = sorted(set(range(expected)) - got)[:8]
        raise HTTPException(status_code=400, detail=f"Missing chunks {missing} — retry the upload")
    try:
        content = assemble_chunks(folder, int(meta.get("size") or 0))
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File exceeds 25 MB limit")
        site = row.site
        doc = store_document_bytes(
            db,
            site,
            content=content,
            filename=str(meta.get("filename") or "upload.bin"),
            content_type=None,
            category=str(meta.get("category") or "other"),
            description=meta.get("description"),
            uploaded_by=meta.get("uploaded_by"),
            moa_number=meta.get("moa_number") or (site.moa_number if site else None),
            visibility=_normalize_visibility(meta.get("visibility")),
            source="comms",
            comms_row_id=row.id,
            allow_missing_site=True,
        )
        notify_from_request(request, site_ids=[row.site_id] if row.site_id else None, reason="comms_doc")
        return _doc_out(doc, site)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
