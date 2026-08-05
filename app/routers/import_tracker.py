"""Upload WRU Traffic TGS-MOA Tracker Excel workbooks."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..database import get_db
from ..tracker_import import import_tracker_rows, parse_tracker_workbook

router = APIRouter(
    prefix="/api/import",
    tags=["import"],
    dependencies=[Depends(require_admin)],
)

MAX_BYTES = 40 * 1024 * 1024


@router.post("/tracker")
async def import_tracker_excel(
    file: UploadFile = File(...),
    update_existing: bool = Query(default=True),
    dry_run: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    name = (file.filename or "").lower()
    if not name.endswith((".xlsx", ".xlsm", ".xls")):
        raise HTTPException(status_code=400, detail="Upload an Excel .xlsx / .xlsm tracker file")
    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 40 MB limit")
    try:
        rows = parse_tracker_workbook(content)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not parse workbook: {exc}") from exc
    if not rows:
        raise HTTPException(status_code=400, detail="No site rows found in the tracker sheet")
    if dry_run:
        return {
            "dry_run": True,
            "parsed": len(rows),
            "sample": [
                {
                    "road_name": r["road_name"],
                    "site_number": r["site_number"],
                    "program": r.get("program"),
                    "status_text": r.get("status_text"),
                    "moa_number": r.get("moa_number"),
                }
                for r in rows[:15]
            ],
        }
    result = import_tracker_rows(db, rows, update_existing=update_existing)
    result["dry_run"] = False
    return result
