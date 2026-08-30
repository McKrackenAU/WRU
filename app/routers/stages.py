"""Admin CRUD for workflow stages and program categories."""

from __future__ import annotations

import re

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..database import get_db
from ..models import ProgramCategory, Site, WorkflowStageDef, WorkflowStep
from ..notify import normalize_tags
from ..stage_registry import ensure_program_seed, ensure_stage_seed

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


class StageIn(BaseModel):
    key: str | None = Field(default=None, max_length=64)
    label: str = Field(min_length=1, max_length=128)
    position: int | None = None
    list_role: str = Field(default="none", pattern="^(none|permits|trims|complete)$")
    counts_toward_progress: bool = True
    active: bool = True


class StageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    label: str
    position: int
    list_role: str
    counts_toward_progress: bool
    active: bool


class ProgramIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    position: int | None = None
    active: bool = True
    tags: list[str] | str | None = None


class ProgramOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    position: int
    active: bool
    tags: list[str] = Field(default_factory=list)


class StageReorderIn(BaseModel):
    ids: list[int] = Field(min_length=1)


def _slug_key(label: str) -> str:
    key = re.sub(r"[^a-zA-Z0-9]+", "_", label.strip().lower()).strip("_")
    return key or "stage"


def program_to_public(row: ProgramCategory) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "position": row.position,
        "active": bool(row.active),
        "tags": normalize_tags(getattr(row, "tags", None)),
    }


def assign_stage_positions(ordered_ids: list[int], all_ids: list[int]) -> dict[int, int]:
    """Map stage ids to 10, 20, 30… following ordered_ids then any leftovers."""
    used: list[int] = []
    seen: set[int] = set()
    for sid in ordered_ids:
        if sid in seen:
            continue
        used.append(sid)
        seen.add(sid)
    for sid in all_ids:
        if sid not in seen:
            used.append(sid)
            seen.add(sid)
    return {sid: (i + 1) * 10 for i, sid in enumerate(used)}


def pick_fold_target(removing_key: str, remaining: list[WorkflowStageDef]) -> str | None:
    """Where to move completed-site flags when a stage is removed."""
    active = [s for s in remaining if s.active and s.key != removing_key]
    complete = [s for s in active if s.list_role == "complete"]
    if complete:
        complete.sort(key=lambda s: (s.position, s.id))
        return complete[-1].key
    if active:
        active.sort(key=lambda s: (s.position, s.id))
        return active[-1].key
    return None


def fold_completed_stage(db: Session, from_key: str, into_key: str) -> int:
    """Copy completed flags from one stage key onto another. Returns sites updated."""
    if from_key == into_key:
        return 0
    now = datetime.now(timezone.utc)
    site_ids = [
        sid
        for (sid,) in db.query(WorkflowStep.site_id)
        .filter(WorkflowStep.stage == from_key, WorkflowStep.completed.is_(True))
        .all()
    ]
    if not site_ids:
        return 0
    targets = {
        step.site_id: step
        for step in db.query(WorkflowStep).filter(
            WorkflowStep.stage == into_key,
            WorkflowStep.site_id.in_(site_ids),
        )
    }
    updated = 0
    for sid in site_ids:
        step = targets.get(sid)
        if step is None:
            db.add(
                WorkflowStep(
                    site_id=sid,
                    stage=into_key,
                    completed=True,
                    completed_at=now,
                )
            )
            updated += 1
            continue
        if not step.completed:
            step.completed = True
            step.completed_at = now
            updated += 1
    return updated


def _backfill_stage_steps(db: Session, stage_key: str) -> None:
    """Ensure every site has a WorkflowStep row for a newly activated stage key.

    If a site is already past a complete-role stage (received / ready for works),
    auto-complete the new step so progress bars do not regress.
    """
    from datetime import datetime, timezone

    from ..stage_registry import active_stages

    site_ids = [sid for (sid,) in db.query(Site.id).all()]
    if not site_ids:
        return
    existing = {
        site_id
        for (site_id,) in db.query(WorkflowStep.site_id)
        .filter(WorkflowStep.stage == stage_key)
        .all()
    }
    complete_keys = {s.key for s in active_stages(db) if s.list_role == "complete"}
    done_complete = {
        site_id
        for (site_id,) in db.query(WorkflowStep.site_id)
        .filter(
            WorkflowStep.stage.in_(complete_keys) if complete_keys else False,
            WorkflowStep.completed.is_(True),
        )
        .all()
    } if complete_keys else set()
    now = datetime.now(timezone.utc)
    for site_id in site_ids:
        if site_id in existing:
            continue
        already_complete = site_id in done_complete
        db.add(
            WorkflowStep(
                site_id=site_id,
                stage=stage_key,
                completed=already_complete,
                completed_at=now if already_complete else None,
            )
        )


@router.get("/stages", response_model=list[StageOut])
def list_stages(
    include_inactive: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    ensure_stage_seed(db)
    q = db.query(WorkflowStageDef)
    if not include_inactive:
        q = q.filter(WorkflowStageDef.active.is_(True))
    return q.order_by(WorkflowStageDef.position.asc(), WorkflowStageDef.id.asc()).all()


@router.post("/stages", response_model=StageOut, status_code=201)
def create_stage(payload: StageIn, db: Session = Depends(get_db)):
    ensure_stage_seed(db)
    key = (payload.key or _slug_key(payload.label)).strip()
    if db.query(WorkflowStageDef).filter(WorkflowStageDef.key == key).first():
        raise HTTPException(status_code=400, detail="Stage key already exists")
    max_pos = db.query(func.max(WorkflowStageDef.position)).scalar() or 0
    row = WorkflowStageDef(
        key=key,
        label=payload.label.strip(),
        position=payload.position if payload.position is not None else max_pos + 10,
        list_role=payload.list_role,
        counts_toward_progress=payload.counts_toward_progress,
        active=payload.active,
    )
    db.add(row)
    db.flush()
    if row.active:
        _backfill_stage_steps(db, row.key)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/stages/{stage_id}", response_model=StageOut)
def update_stage(stage_id: int, payload: StageIn, db: Session = Depends(get_db)):
    row = db.get(WorkflowStageDef, stage_id)
    if not row:
        raise HTTPException(status_code=404, detail="Stage not found")
    was_active = row.active
    row.label = payload.label.strip()
    if payload.position is not None:
        row.position = payload.position
    row.list_role = payload.list_role
    row.counts_toward_progress = payload.counts_toward_progress
    row.active = payload.active
    if row.active and not was_active:
        _backfill_stage_steps(db, row.key)
    db.commit()
    db.refresh(row)
    return row


@router.put("/stages/order", response_model=list[StageOut])
def reorder_stages(payload: StageReorderIn, db: Session = Depends(get_db)):
    """Set workflow order. Register dropdown, progress bar, and status advance follow this."""
    ensure_stage_seed(db)
    rows = db.query(WorkflowStageDef).all()
    by_id = {r.id: r for r in rows}
    unknown = [sid for sid in payload.ids if sid not in by_id]
    if unknown:
        raise HTTPException(status_code=400, detail="Unknown stage id in order")
    leftovers = sorted(rows, key=lambda r: (r.position, r.id))
    positions = assign_stage_positions(payload.ids, [r.id for r in leftovers])
    for row in rows:
        row.position = positions[row.id]
    db.commit()
    return (
        db.query(WorkflowStageDef)
        .order_by(WorkflowStageDef.position.asc(), WorkflowStageDef.id.asc())
        .all()
    )


@router.delete("/stages/{stage_id}", status_code=204)
def delete_stage(stage_id: int, db: Session = Depends(get_db)):
    row = db.get(WorkflowStageDef, stage_id)
    if not row:
        raise HTTPException(status_code=404, detail="Stage not found")
    others = [s for s in db.query(WorkflowStageDef).all() if s.id != row.id]
    if row.active and not any(s.active for s in others):
        raise HTTPException(status_code=400, detail="Keep at least one active stage")
    target = pick_fold_target(row.key, others)
    if target:
        fold_completed_stage(db, row.key, target)
    row.active = False
    db.commit()
    return None


@router.get("/programs", response_model=list[ProgramOut])
def list_programs(db: Session = Depends(get_db)):
    ensure_program_seed(db)
    rows = (
        db.query(ProgramCategory)
        .order_by(ProgramCategory.position.asc(), ProgramCategory.id.asc())
        .all()
    )
    return [program_to_public(row) for row in rows]


@router.post("/programs", response_model=ProgramOut, status_code=201)
def create_program(payload: ProgramIn, db: Session = Depends(get_db)):
    ensure_program_seed(db)
    if (
        db.query(ProgramCategory)
        .filter(func.lower(ProgramCategory.name) == payload.name.strip().lower())
        .first()
    ):
        raise HTTPException(status_code=400, detail="Program already exists")
    max_pos = db.query(func.max(ProgramCategory.position)).scalar() or 0
    row = ProgramCategory(
        name=payload.name.strip(),
        position=payload.position if payload.position is not None else max_pos + 10,
        active=payload.active,
        tags=normalize_tags(payload.tags),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return program_to_public(row)


@router.patch("/programs/{program_id}", response_model=ProgramOut)
def update_program(program_id: int, payload: ProgramIn, db: Session = Depends(get_db)):
    row = db.get(ProgramCategory, program_id)
    if not row:
        raise HTTPException(status_code=404, detail="Program not found")
    clash = (
        db.query(ProgramCategory)
        .filter(
            func.lower(ProgramCategory.name) == payload.name.strip().lower(),
            ProgramCategory.id != program_id,
        )
        .first()
    )
    if clash:
        raise HTTPException(status_code=400, detail="Program already exists")
    row.name = payload.name.strip()
    if payload.position is not None:
        row.position = payload.position
    row.active = payload.active
    if payload.tags is not None:
        row.tags = normalize_tags(payload.tags)
    db.commit()
    db.refresh(row)
    return program_to_public(row)


@router.delete("/programs/{program_id}", status_code=204)
def delete_program(program_id: int, db: Session = Depends(get_db)):
    row = db.get(ProgramCategory, program_id)
    if not row:
        raise HTTPException(status_code=404, detail="Program not found")
    row.active = False
    db.commit()
    return None
