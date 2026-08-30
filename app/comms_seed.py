"""Seed FMRP / Maintenance comms planner sheets from bundled JSON."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import CommsColumn, CommsRow, CommsSheet, Site
from .services import slugify_field_key

SEED_PATH = Path(__file__).resolve().parent / "comms_seed_data.json"


def _load_payload() -> dict:
    if not SEED_PATH.is_file():
        return {"sheets": []}
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def _match_site(db: Session, values: dict) -> int | None:
    site_number = (
        str(values.get("site_number") or values.get("structure_number") or "").strip()
    )
    if site_number:
        row = (
            db.query(Site)
            .filter(func.lower(Site.site_number) == site_number.lower())
            .first()
        )
        if row:
            return row.id
    road = str(values.get("road_street_name") or values.get("location") or "").strip()
    if road:
        row = (
            db.query(Site)
            .filter(func.lower(Site.road_name) == road.lower())
            .first()
        )
        if row:
            return row.id
        row = (
            db.query(Site)
            .filter(Site.road_name.ilike(f"%{road}%"))
            .first()
        )
        if row:
            return row.id
    return None


def ensure_comms_seed(db: Session) -> None:
    """Create the two bundled planner sheets when the comms section is empty."""
    if db.query(CommsSheet).count() > 0:
        return
    payload = _load_payload()
    sheets = payload.get("sheets") or []
    if not sheets:
        return
    for index, raw in enumerate(sheets):
        key = slugify_field_key(str(raw.get("key") or f"sheet_{index + 1}"))
        sheet = CommsSheet(
            key=key,
            title=(raw.get("title") or key).strip()[:128],
            description=(raw.get("description") or "").strip()[:255] or None,
            position=index,
            seeded=True,
        )
        db.add(sheet)
        db.flush()
        used_keys: set[str] = set()
        for pos, col in enumerate(raw.get("columns") or []):
            name = str(col.get("name") or "Column").strip()[:128] or "Column"
            field_key = slugify_field_key(str(col.get("field_key") or name))
            base = field_key
            suffix = 2
            while field_key in used_keys:
                field_key = f"{base}_{suffix}"
                suffix += 1
            used_keys.add(field_key)
            ftype = str(col.get("field_type") or "text")
            if ftype not in {"text", "number", "date", "checkbox", "select"}:
                ftype = "text"
            options = col.get("options")
            if options is not None and not isinstance(options, list):
                options = None
            db.add(
                CommsColumn(
                    sheet_id=sheet.id,
                    name=name,
                    field_key=field_key,
                    field_type=ftype,
                    options=options,
                    position=pos,
                    created_by="seed",
                )
            )
        for pos, row in enumerate(raw.get("rows") or []):
            values = dict(row.get("values") or {})
            db.add(
                CommsRow(
                    sheet_id=sheet.id,
                    position=pos,
                    section=(row.get("section") or values.get("workpack") or None),
                    values=values,
                    site_id=_match_site(db, values),
                    created_by="seed",
                )
            )
    db.commit()


def ensure_comms_resources(db: Session) -> None:
    """Tables only — headings and links are created by the comms team."""
    return
