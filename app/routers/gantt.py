"""Program Gantt boards with reactive site sequencing."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..gantt_engine import recompute_board_dates
from ..models import AsphaltSubcontractor, GanttBoard, GanttItem, Site
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
    link_mode: str = Field(default="after_previous", pattern="^(after_previous|fixed_start)$")
    fixed_start: date | None = None
    subcontractor_id: int | None = None
    rdo_dates: list[str] = Field(default_factory=list)
    exclude_dates: list[str] = Field(default_factory=list)
    include_dates: list[str] = Field(default_factory=list)
    notes: str | None = None
    position: int | None = None


class ItemPatch(BaseModel):
    shifts_count: int | None = Field(default=None, ge=1, le=365)
    link_mode: str | None = Field(default=None, pattern="^(after_previous|fixed_start)$")
    fixed_start: date | None = None
    subcontractor_id: int | None = None
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


def _recompute_and_save(db: Session, board: GanttBoard) -> dict:
    items = (
        db.query(GanttItem)
        .options(selectinload(GanttItem.site), selectinload(GanttItem.subcontractor))
        .filter(GanttItem.board_id == board.id)
        .order_by(GanttItem.position.asc(), GanttItem.id.asc())
        .all()
    )
    out = recompute_board_dates(board, items, subcontractors_by_id=_subs_map(db))
    # Keep the sites register start dates in sync with the cascade
    for item in items:
        if item.site and item.planned_start:
            item.site.indicative_site_start_date = item.planned_start
    db.commit()
    return _board_public(board, out)


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
    return _recompute_and_save(db, board)


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
    max_pos = (
        db.query(GanttItem.position)
        .filter(GanttItem.board_id == board.id)
        .order_by(GanttItem.position.desc())
        .limit(1)
        .scalar()
    )
    pos = payload.position if payload.position is not None else (max_pos or 0) + 10
    item = GanttItem(
        board_id=board.id,
        site_id=payload.site_id,
        position=pos,
        shifts_count=payload.shifts_count,
        link_mode=payload.link_mode,
        fixed_start=payload.fixed_start,
        subcontractor_id=payload.subcontractor_id,
        rdo_dates=payload.rdo_dates or [],
        exclude_dates=payload.exclude_dates or [],
        include_dates=payload.include_dates or [],
        notes=payload.notes,
    )
    db.add(item)
    db.commit()
    return _recompute_and_save(db, board)


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
    if "subcontractor_id" in data and data["subcontractor_id"] is not None:
        if not db.get(AsphaltSubcontractor, data["subcontractor_id"]):
            raise HTTPException(status_code=404, detail="Subcontractor not found")
    for key, value in data.items():
        setattr(item, key, value)
    db.commit()
    return _recompute_and_save(db, board)


@router.post("/board/reorder")
def reorder_items(
    payload: ReorderIn,
    program: str = Query(default=DEFAULT_GANTT_PROGRAM),
    db: Session = Depends(get_db),
):
    board = _load_board(db, program)
    items = (
        db.query(GanttItem)
        .filter(GanttItem.board_id == board.id, GanttItem.id.in_(payload.item_ids))
        .all()
    )
    by_id = {i.id: i for i in items}
    if len(by_id) != len(set(payload.item_ids)):
        raise HTTPException(status_code=400, detail="One or more items are not on this board")
    for idx, item_id in enumerate(payload.item_ids):
        by_id[item_id].position = (idx + 1) * 10
    db.commit()
    return _recompute_and_save(db, board)


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
    """Add missing active sites for this program onto the board (end of sequence)."""
    board = _load_board(db, program)
    existing = {
        i.site_id
        for i in db.query(GanttItem.site_id).filter(GanttItem.board_id == board.id).all()
    }
    sites = (
        db.query(Site)
        .filter(Site.archived.is_(False), Site.program == board.program)
        .order_by(Site.indicative_site_start_date.asc().nullslast(), Site.id.asc())
        .all()
    )
    max_pos = (
        db.query(GanttItem.position)
        .filter(GanttItem.board_id == board.id)
        .order_by(GanttItem.position.desc())
        .limit(1)
        .scalar()
        or 0
    )
    added = 0
    for site in sites:
        if site.id in existing:
            continue
        max_pos += 10
        db.add(
            GanttItem(
                board_id=board.id,
                site_id=site.id,
                position=max_pos,
                shifts_count=1,
                link_mode="after_previous",
                fixed_start=None,
            )
        )
        added += 1
    db.commit()
    out = _recompute_and_save(db, board)
    out["synced_added"] = added
    return out
