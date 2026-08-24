"""Upload WRU Traffic TGS-MOA Tracker Excel workbooks."""

from __future__ import annotations

from zipfile import BadZipFile

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
    if name.endswith(".xls") and not name.endswith(".xlsx") and not name.endswith(".xlsm"):
        raise HTTPException(
            status_code=400,
            detail="Legacy .xls is not supported. Save the tracker as .xlsx or .xlsm (Excel → Save As) and retry.",
        )
    if not name.endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Upload an Excel .xlsx / .xlsm tracker file")
    content = await file.read()
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
                }
                for r in rows[:20]
            ],
        }
    result = import_tracker_rows(db, rows, update_existing=update_existing)
    result["dry_run"] = False
    result["sheet_name"] = parsed.get("sheet_name")
    result["unmatched_statuses"] = parsed.get("unmatched_statuses") or []
    return result
