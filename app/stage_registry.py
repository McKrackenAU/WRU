"""Load configurable workflow stages and program categories from the DB."""

from __future__ import annotations

from sqlalchemy.orm import Session

from .models import ProgramCategory, WorkflowStageDef

# Seeded defaults — keys stay stable so existing WorkflowStep rows keep working.
DEFAULT_STAGES: list[dict] = [
    {
        "key": "tgs_markup_completed",
        "label": "TGS Markup completed",
        "position": 10,
        "list_role": "none",
        "counts_toward_progress": True,
    },
    {
        "key": "submitted_to_tmd",
        "label": "Submitted to traffic management (waiting for plans)",
        "position": 20,
        "list_role": "none",
        "counts_toward_progress": True,
    },
    {
        "key": "ventia_review",
        "label": "Ventia review",
        "position": 30,
        "list_role": "none",
        "counts_toward_progress": True,
    },
    {
        "key": "plan_received",
        "label": "Plan received",
        "position": 40,
        "list_role": "none",
        "counts_toward_progress": True,
    },
    {
        "key": "ready_to_submit_moa",
        "label": "Waiting to submit to DTP",
        "position": 50,
        "list_role": "none",
        "counts_toward_progress": True,
    },
    {
        "key": "moa_submitted",
        "label": "MoA submitted (Permits team)",
        "position": 60,
        "list_role": "permits",
        "counts_toward_progress": True,
    },
    {
        "key": "moa_with_trims",
        "label": "MoA with TRIMS team",
        "position": 70,
        "list_role": "trims",
        "counts_toward_progress": True,
    },
    {
        "key": "revision_needed",
        "label": "Revision needed",
        "position": 80,
        "list_role": "permits",
        "counts_toward_progress": False,
    },
    {
        "key": "moa_received",
        "label": "MoA received / approved",
        "position": 90,
        "list_role": "complete",
        "counts_toward_progress": True,
    },
    {
        "key": "ready_for_works",
        "label": "Ready for works",
        "position": 100,
        "list_role": "complete",
        "counts_toward_progress": True,
    },
]

DEFAULT_PROGRAMS = [
    ("Lifecycle pavements", 10),
    ("Lifecycle structures", 20),
    ("Assets", 30),
    ("Routine maintenance", 40),
]


def ensure_stage_seed(db: Session) -> None:
    existing = {r.key: r for r in db.query(WorkflowStageDef).all()}
    changed = False
    for row in DEFAULT_STAGES:
        if row["key"] in existing:
            continue
        db.add(
            WorkflowStageDef(
                key=row["key"],
                label=row["label"],
                position=row["position"],
                list_role=row["list_role"],
                counts_toward_progress=row["counts_toward_progress"],
                active=True,
            )
        )
        changed = True
    if changed:
        db.commit()


def ensure_program_seed(db: Session) -> None:
    existing = {r.name.lower() for r in db.query(ProgramCategory).all()}
    changed = False
    for name, pos in DEFAULT_PROGRAMS:
        if name.lower() in existing:
            continue
        db.add(ProgramCategory(name=name, position=pos, active=True))
        changed = True
    if changed:
        db.commit()


def active_stages(db: Session) -> list[WorkflowStageDef]:
    ensure_stage_seed(db)
    return (
        db.query(WorkflowStageDef)
        .filter(WorkflowStageDef.active.is_(True))
        .order_by(WorkflowStageDef.position.asc(), WorkflowStageDef.id.asc())
        .all()
    )


def all_stages(db: Session) -> list[WorkflowStageDef]:
    ensure_stage_seed(db)
    return (
        db.query(WorkflowStageDef)
        .order_by(WorkflowStageDef.position.asc(), WorkflowStageDef.id.asc())
        .all()
    )


def stage_keys(db: Session) -> list[str]:
    return [s.key for s in active_stages(db)]


def stage_meta(db: Session) -> list[dict]:
    return [
        {
            "key": s.key,
            "label": s.label,
            "position": s.position,
            "list_role": s.list_role,
            "counts_toward_progress": s.counts_toward_progress,
            "active": s.active,
        }
        for s in active_stages(db)
    ]


def stage_labels_map(db: Session) -> dict[str, str]:
    return {s.key: s.label for s in all_stages(db)}


def active_programs(db: Session) -> list[str]:
    ensure_program_seed(db)
    rows = (
        db.query(ProgramCategory)
        .filter(ProgramCategory.active.is_(True))
        .order_by(ProgramCategory.position.asc(), ProgramCategory.id.asc())
        .all()
    )
    return [r.name for r in rows]
