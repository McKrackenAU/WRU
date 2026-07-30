from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import CustomColumn, Site
from ..schemas import CustomColumnCreate, CustomColumnOut, CustomColumnUpdate
from ..services import slugify_field_key

router = APIRouter(prefix="/api/columns", tags=["columns"])


@router.get("", response_model=list[CustomColumnOut])
def list_columns(db: Session = Depends(get_db)):
    return (
        db.query(CustomColumn)
        .order_by(CustomColumn.position.asc(), CustomColumn.id.asc())
        .all()
    )


@router.post("", response_model=CustomColumnOut, status_code=201)
def create_column(payload: CustomColumnCreate, db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Column name is required")

    base_key = slugify_field_key(name)
    field_key = base_key
    suffix = 2
    while db.query(CustomColumn).filter(CustomColumn.field_key == field_key).first():
        field_key = f"{base_key}_{suffix}"
        suffix += 1

    if db.query(CustomColumn).filter(func.lower(CustomColumn.name) == name.lower()).first():
        raise HTTPException(status_code=400, detail="A column with this name already exists")

    max_pos = db.query(func.max(CustomColumn.position)).scalar()
    column = CustomColumn(
        name=name,
        field_key=field_key,
        field_type=payload.field_type,
        options=payload.options,
        position=(max_pos or 0) + 1,
        created_by=payload.created_by,
    )
    db.add(column)
    db.commit()
    db.refresh(column)
    return column


@router.patch("/{column_id}", response_model=CustomColumnOut)
def update_column(column_id: int, payload: CustomColumnUpdate, db: Session = Depends(get_db)):
    column = db.get(CustomColumn, column_id)
    if not column:
        raise HTTPException(status_code=404, detail="Column not found")

    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        data["name"] = data["name"].strip()
        clash = (
            db.query(CustomColumn)
            .filter(
                func.lower(CustomColumn.name) == data["name"].lower(),
                CustomColumn.id != column_id,
            )
            .first()
        )
        if clash:
            raise HTTPException(status_code=400, detail="A column with this name already exists")

    for key, value in data.items():
        setattr(column, key, value)

    db.commit()
    db.refresh(column)
    return column


@router.delete("/{column_id}", status_code=204)
def delete_column(column_id: int, db: Session = Depends(get_db)):
    column = db.get(CustomColumn, column_id)
    if not column:
        raise HTTPException(status_code=404, detail="Column not found")

    field_key = column.field_key
    sites = db.query(Site).all()
    for site in sites:
        fields = dict(site.custom_fields or {})
        if field_key in fields:
            fields.pop(field_key, None)
            site.custom_fields = fields

    db.delete(column)
    db.commit()
    return None
