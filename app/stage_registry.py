"""Load configurable workflow stages and program categories from the DB."""

from __future__ import annotations

from sqlalchemy.orm import Session

from .models import ProgramCategory, WorkflowStageDef

# Seeded defaults — keys stay stable so existing WorkflowStep rows keep working.
# Labels / roles match WRU Traffic TGS-MOA Tracker V6 spreadsheet statuses.
DEFAULT_STAGES: list[dict] = [
    {
        "key": "tgs_markup_completed",
        "label": "TGS Markup Complete",
        "position": 10,
        "list_role": "none",
        "counts_toward_progress": True,
        "active": True,
    },
    {
        "key": "submitted_to_tmd",
        "label": "Submitted to TMD",
        "position": 20,
        "list_role": "none",
        "counts_toward_progress": True,
        "active": True,
    },
    {
        "key": "ventia_review",
        "label": "Ventia review",
        "position": 30,
        "list_role": "none",
        "counts_toward_progress": True,
        "active": False,  # not in spreadsheet V6 — available if admins enable
    },
    {
        "key": "plan_received",
        "label": "Plan Received",
        "position": 40,
        "list_role": "none",
        "counts_toward_progress": True,
        "active": True,
    },
    {
        "key": "ready_to_submit_moa",
        "label": "Ready to Submit MoA",
        "position": 50,
        "list_role": "none",
        "counts_toward_progress": True,
        "active": True,
    },
    {
        "key": "moa_submitted",
        "label": "MoA Submitted",
        "position": 60,
        "list_role": "permits",
        "counts_toward_progress": True,
        "active": True,
    },
    {
        "key": "moa_with_trims",
        "label": "MoA With TRIMS",
        "position": 70,
        "list_role": "trims",
        "counts_toward_progress": True,
        "active": True,
    },
    {
        "key": "revision_needed",
        "label": "Revision Needed",
        "position": 80,
        "list_role": "permits",
        "counts_toward_progress": False,
        "active": True,
    },
    {
        "key": "moa_received",
        "label": "MoA Received",
        "position": 90,
        "list_role": "complete",
        "counts_toward_progress": True,
        "active": True,
    },
    {
        "key": "ready_for_works",
        "label": "Ready for Works",
        "position": 100,
        "list_role": "complete",
        "counts_toward_progress": True,
        "active": True,
    },
]

DEFAULT_PROGRAMS = [
    ("LCP-FMRP", 10),
    ("FMRP Non-Commit", 20),
    ("LCP Maintenance Misc", 30),
    ("Structures", 40),
    ("Generics MTMP/ITMP", 50),
    ("Routine Maintenance", 60),
    ("Lifecycle pavements", 70),
    ("Lifecycle structures", 80),
    ("Assets", 90),
]

DEFAULT_COUNCILS = [
    "Hobsons Bay",
    "Maribyrnong",
    "Melbourne",
    "Moonee Valley",
    "Brimbank",
    "Wyndham",
    "Other",
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
                active=bool(row.get("active", True)),
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


def ensure_lookup_seed(db: Session) -> None:
    from .lookups import sync_usage_into_lookups
    from .models import LookupItem

    existing = {
        (r.kind, r.value.lower())
        for r in db.query(LookupItem).filter(LookupItem.kind == "council").all()
    }
    changed = False
    for i, name in enumerate(DEFAULT_COUNCILS):
        if ("council", name.lower()) in existing:
            continue
        db.add(LookupItem(kind="council", value=name, position=(i + 1) * 10, active=True))
        changed = True
    if changed:
        db.commit()
    sync_usage_into_lookups(db, "road")
    sync_usage_into_lookups(db, "council")


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
