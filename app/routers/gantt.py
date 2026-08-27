"""Program Gantt boards with reactive site sequencing."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..gantt_engine import normalize_shift_type, recompute_board_dates
from ..gantt_export import build_gantt_pdf
from ..models import AsphaltSubcontractor, GanttBoard, GanttItem, Site, TrafficContractor
from ..services import sync_computed_fields

router = APIRouter(prefix="/api/gantt", tags=["gantt"])

DEFAULT_GANTT_PROGRAM = "Lifecycle pavements"


class BoardPatch(BaseModel):
    enabled: bool | None = None
    anchor_start: date | None = None
    work_weekdays: list[int] | None = None
    skip_public_holidays: bool | None = None
    skip_sunday_before_monday_ph: bool | None = None
    rdo_dates: list[str] | None = None
    exclude_dates: list[str] | None = None
    include_dates: list[str] | None = None


class ItemIn(BaseModel):
    site_id: int
    shifts_count: int = Field(default=1, ge=1, le=365)
    shift_type: str = Field(default="day", pattern="^(day|night)$")
    link_mode: str = Field(default="after_previous", pattern="^(after_previous|fixed_start)$")
    fixed_start: date | None = None
    subcontractor_id: int | None = None
    traffic_contractor_id: int | None = None
    rdo_dates: list[str] = Field(default_factory=list)
    exclude_dates: list[str] = Field(default_factory=list)
    include_dates: list[str] = Field(default_factory=list)
    notes: str | None = None
    position: int | None = None


class ItemPatch(BaseModel):
    shifts_count: int | None = Field(default=None, ge=1, le=365)
    shift_type: str | None = Field(default=None, pattern="^(day|night)$")
    link_mode: str | None = Field(default=None, pattern="^(after_previous|fixed_start)$")
    fixed_start: date | None = None
    subcontractor_id: int | None = None
    traffic_contractor_id: int | None = None
    rdo_dates: list[str] | None = None
    exclude_dates: list[str] | None = None
    include_dates: list[str] | None = None
    notes: str | None = None


class ReorderIn(BaseModel):
    item_ids: list[int] = Field(min_length=1)


def _subs_map(db: Session) -> dict[int, AsphaltSubcontractor]:
    return {s.id: s for s in db.query(AsphaltSubcontractor).all()}


def _board_public(board: GanttBoard, items_out: list[dict]) -> dict:
    return {
        "id": board.id,
        "program": board.program,
        "enabled": bool(board.enabled),
        "anchor_start": board.anchor_start.isoformat() if board.anchor_start else None,
        "work_weekdays": list(board.work_weekdays or [0, 1, 2, 3, 4]),
        "skip_public_holidays": bool(board.skip_public_holidays),
        "skip_sunday_before_monday_ph": bool(board.skip_sunday_before_monday_ph),
        "rdo_dates": list(board.rdo_dates or []),
        "exclude_dates": list(board.exclude_dates or []),
        "include_dates": list(board.include_dates or []),
        "items": items_out,
    }


def _load_board(db: Session, program: str) -> GanttBoard:
    prog = (program or "").strip() or DEFAULT_GANTT_PROGRAM
    board = db.query(GanttBoard).filter(GanttBoard.program == prog).first()
    if board:
        return board
    board = GanttBoard(program=prog, enabled=True)
    db.add(board)
    db.commit()
    db.refresh(board)
    return board


def _recompute_and_save(db: Session, board: GanttBoard, *, write_back_sites: bool = False) -> dict:
    items = (
        db.query(GanttItem)
        .options(
            selectinload(GanttItem.site),
            selectinload(GanttItem.subcontractor),
            selectinload(GanttItem.traffic_contractor),
        )
        .filter(GanttItem.board_id == board.id)
        .order_by(GanttItem.position.asc(), GanttItem.id.asc())
        .all()
    )
    out = recompute_board_dates(board, items, subcontractors_by_id=_subs_map(db))
    # Only push cascade results back onto the sites register (not initial fixed starts)
    if write_back_sites:
        for item in items:
            if item.site and item.planned_start and (item.link_mode or "") == "after_previous":
                item.site.indicative_site_start_date = item.planned_start
                sync_computed_fields(item.site, db)
    db.commit()
    return _board_public(board, out)


def _auto_populate_board(db: Session, board: GanttBoard) -> int:
    """Ensure all active program sites are on the board, seeded from indicative starts."""
    existing_items = (
        db.query(GanttItem)
        .options(selectinload(GanttItem.site))
        .filter(GanttItem.board_id == board.id)
        .all()
    )
    by_site = {i.site_id: i for i in existing_items}
    sites = (
        db.query(Site)
        .filter(Site.archived.is_(False), Site.program == board.program)
        .order_by(Site.indicative_site_start_date.asc().nullslast(), Site.id.asc())
        .all()
    )
    added = 0
    # Position by indicative start so the chart reads in calendar order
    for idx, site in enumerate(sites):
        pos = (idx + 1) * 10
        item = by_site.get(site.id)
        if item is None:
            item = GanttItem(
                board_id=board.id,
                site_id=site.id,
                position=pos,
                shifts_count=1,
                link_mode="fixed_start" if site.indicative_site_start_date else "after_previous",
                fixed_start=site.indicative_site_start_date,
            )
            db.add(item)
            added += 1
        else:
            # Keep chart ordered by indicative start until the user reorders (cascade mode)
            if (item.link_mode or "") != "after_previous":
                item.position = pos
                if site.indicative_site_start_date:
                    item.link_mode = "fixed_start"
                    item.fixed_start = site.indicative_site_start_date

    starts = [s.indicative_site_start_date for s in sites if s.indicative_site_start_date]
    if starts and board.anchor_start is None:
        board.anchor_start = min(starts)
    db.commit()
    return added


@router.get("/boards")
def list_boards(db: Session = Depends(get_db)):
    rows = db.query(GanttBoard).order_by(GanttBoard.program.asc()).all()
    return [
        {
            "id": b.id,
            "program": b.program,
            "enabled": bool(b.enabled),
            "anchor_start": b.anchor_start.isoformat() if b.anchor_start else None,
            "item_count": db.query(GanttItem).filter(GanttItem.board_id == b.id).count(),
        }
        for b in rows
    ]


@router.get("/board")
def get_board(program: str = Query(default=DEFAULT_GANTT_PROGRAM), db: Session = Depends(get_db)):
    board = _load_board(db, program)
    _auto_populate_board(db, board)
    return _recompute_and_save(db, board, write_back_sites=False)


@router.patch("/board")
def patch_board(
    payload: BoardPatch,
    program: str = Query(default=DEFAULT_GANTT_PROGRAM),
    db: Session = Depends(get_db),
):
    board = _load_board(db, program)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(board, key, value)
    db.commit()
    db.refresh(board)
    return _recompute_and_save(db, board)


@router.post("/board/items", status_code=201)
def add_item(
    payload: ItemIn,
    program: str = Query(default=DEFAULT_GANTT_PROGRAM),
    db: Session = Depends(get_db),
):
    board = _load_board(db, program)
    site = db.get(Site, payload.site_id)
    if not site or site.archived:
        raise HTTPException(status_code=404, detail="Active site not found")
    if (
        db.query(GanttItem)
        .filter(GanttItem.board_id == board.id, GanttItem.site_id == payload.site_id)
        .first()
    ):
        raise HTTPException(status_code=400, detail="Site is already on this Gantt")
    if payload.subcontractor_id and not db.get(AsphaltSubcontractor, payload.subcontractor_id):
        raise HTTPException(status_code=404, detail="Subcontractor not found")
    if payload.traffic_contractor_id and not db.get(TrafficContractor, payload.traffic_contractor_id):
        raise HTTPException(status_code=404, detail="Traffic contractor not found")
    max_pos = (
        db.query(GanttItem.position)
        .filter(GanttItem.board_id == board.id)
        .order_by(GanttItem.position.desc())
        .limit(1)
        .scalar()
    )
    pos = payload.position if payload.position is not None else (max_pos or 0) + 10
    fixed = payload.fixed_start or site.indicative_site_start_date
    link_mode = payload.link_mode
    if payload.fixed_start is None and site.indicative_site_start_date and link_mode == "after_previous":
        # Prefer parking new sites on their indicative start until the chart is reordered
        link_mode = "fixed_start"
    item = GanttItem(
        board_id=board.id,
        site_id=payload.site_id,
        position=pos,
        shifts_count=payload.shifts_count,
        shift_type=normalize_shift_type(payload.shift_type),
        link_mode=link_mode,
        fixed_start=fixed if link_mode == "fixed_start" else payload.fixed_start,
        subcontractor_id=payload.subcontractor_id,
        traffic_contractor_id=payload.traffic_contractor_id,
        rdo_dates=payload.rdo_dates or [],
        exclude_dates=payload.exclude_dates or [],
        include_dates=payload.include_dates or [],
        notes=payload.notes,
    )
    db.add(item)
    db.commit()
    return _recompute_and_save(db, board, write_back_sites=False)


@router.patch("/board/items/{item_id}")
def patch_item(
    item_id: int,
    payload: ItemPatch,
    program: str = Query(default=DEFAULT_GANTT_PROGRAM),
    db: Session = Depends(get_db),
):
    board = _load_board(db, program)
    item = db.get(GanttItem, item_id)
    if not item or item.board_id != board.id:
        raise HTTPException(status_code=404, detail="Gantt item not found")
    data = payload.model_dump(exclude_unset=True)
    if "shift_type" in data and data["shift_type"] is not None:
        data["shift_type"] = normalize_shift_type(data["shift_type"])
    if "subcontractor_id" in data and data["subcontractor_id"] is not None:
        if not db.get(AsphaltSubcontractor, data["subcontractor_id"]):
            raise HTTPException(status_code=404, detail="Subcontractor not found")
    if "traffic_contractor_id" in data and data["traffic_contractor_id"] is not None:
        if not db.get(TrafficContractor, data["traffic_contractor_id"]):
            raise HTTPException(status_code=404, detail="Traffic contractor not found")
    for key, value in data.items():
        setattr(item, key, value)
    db.commit()
    cascading = (
        db.query(GanttItem)
        .filter(GanttItem.board_id == board.id, GanttItem.link_mode == "after_previous")
        .count()
        > 0
    )
    return _recompute_and_save(db, board, write_back_sites=cascading)


@router.post("/board/reorder")
def reorder_items(
    payload: ReorderIn,
    program: str = Query(default=DEFAULT_GANTT_PROGRAM),
    db: Session = Depends(get_db),
):
    """Reorder items and switch into cascading schedule mode from the new first site."""
    board = _load_board(db, program)
    items = (
        db.query(GanttItem)
        .options(selectinload(GanttItem.site))
        .filter(GanttItem.board_id == board.id, GanttItem.id.in_(payload.item_ids))
        .all()
    )
    by_id = {i.id: i for i in items}
    if len(by_id) != len(set(payload.item_ids)):
        raise HTTPException(status_code=400, detail="One or more items are not on this board")

    first = by_id[payload.item_ids[0]]
    # Anchor the cascade at the dragged-to-top site's current / indicative start
    anchor = (
        first.planned_start
        or first.fixed_start
        or (first.site.indicative_site_start_date if first.site else None)
        or board.anchor_start
    )
    if anchor:
        board.anchor_start = anchor

    for idx, item_id in enumerate(payload.item_ids):
        item = by_id[item_id]
        item.position = (idx + 1) * 10
        if idx == 0:
            item.link_mode = "fixed_start"
            item.fixed_start = anchor
        else:
            item.link_mode = "after_previous"
            item.fixed_start = None
    db.commit()
    return _recompute_and_save(db, board, write_back_sites=True)


@router.delete("/board/items/{item_id}", status_code=200)
def delete_item(
    item_id: int,
    program: str = Query(default=DEFAULT_GANTT_PROGRAM),
    db: Session = Depends(get_db),
):
    board = _load_board(db, program)
    item = db.get(GanttItem, item_id)
    if not item or item.board_id != board.id:
        raise HTTPException(status_code=404, detail="Gantt item not found")
    db.delete(item)
    db.commit()
    return _recompute_and_save(db, board)


@router.post("/board/sync-program-sites")
def sync_program_sites(
    program: str = Query(default=DEFAULT_GANTT_PROGRAM),
    db: Session = Depends(get_db),
):
    """Refresh the board from active program sites and their indicative start dates."""
    board = _load_board(db, program)
    added = _auto_populate_board(db, board)
    out = _recompute_and_save(db, board, write_back_sites=False)
    out["synced_added"] = added
    return out


@router.get("/board/export.pdf")
def export_board_pdf(
    program: str = Query(default=DEFAULT_GANTT_PROGRAM),
    subcontractor_id: int | None = Query(default=None),
    traffic_contractor_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """MS Project–style landscape Gantt PDF (whole board or by contractor)."""
    board = _load_board(db, program)
    _auto_populate_board(db, board)
    payload = _recompute_and_save(db, board, write_back_sites=False)
    items = list(payload.get("items") or [])
    filter_bits: list[str] = []
    if subcontractor_id:
        sub = db.get(AsphaltSubcontractor, subcontractor_id)
        if not sub:
            raise HTTPException(status_code=404, detail="Asphalt subcontractor not found")
        items = [i for i in items if i.get("subcontractor_id") == subcontractor_id]
        filter_bits.append(f"Asphalt: {sub.name}")
    if traffic_contractor_id:
        traffic = db.get(TrafficContractor, traffic_contractor_id)
        if not traffic:
            raise HTTPException(status_code=404, detail="Traffic contractor not found")
        items = [i for i in items if i.get("traffic_contractor_id") == traffic_contractor_id]
        filter_bits.append(f"Traffic: {traffic.name}")
    payload = {**payload, "items": items}
    pdf = build_gantt_pdf(payload, filter_label=" · ".join(filter_bits) if filter_bits else None)
    safe_prog = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (program or "gantt"))[:48]
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="gantt-{safe_prog}.pdf"'},
    )
