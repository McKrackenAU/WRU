from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import distinct
from sqlalchemy.orm import Session

from .database import get_db
from .financial_year import fy_choices
from .migrate import run_migrations
from .models import DOC_CATEGORIES, LookupItem, Site, SiteCouncil
from .routers import (
    columns,
    costs,
    dashboard,
    documents,
    export,
    import_tracker,
    map_layers,
    settings_admin,
    sites,
    stages,
    system,
    tracking,
)
from .schemas import MetaOut
from .settings_store import get_rules
from .stage_registry import active_programs, ensure_lookup_seed, stage_meta
from .version import version_string

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="WRU TGS Tracker",
    description="Ventia-styled traffic guidance / MoA workflow tracker with custom columns, tracking, documents, archive, and map.",
    version=version_string(),
)

run_migrations()

app.include_router(sites.router)
app.include_router(columns.router)
app.include_router(tracking.router)
app.include_router(documents.router)
app.include_router(dashboard.router)
app.include_router(export.router)
app.include_router(map_layers.router)
app.include_router(costs.router)
app.include_router(stages.router)
app.include_router(settings_admin.router)
app.include_router(import_tracker.router)
app.include_router(system.router)


@app.get("/api/meta", response_model=MetaOut)
def meta(db: Session = Depends(get_db)):
    rules = get_rules(db)
    ensure_lookup_seed(db)
    seeded_programs = active_programs(db)
    used_programs = [
        p
        for (p,) in db.query(distinct(Site.program)).filter(Site.program.isnot(None)).order_by(Site.program).all()
        if p
    ]
    programs = list(dict.fromkeys([*seeded_programs, *used_programs]))
    lookup_councils = [
        r.value
        for r in db.query(LookupItem)
        .filter(LookupItem.kind == "council", LookupItem.active.is_(True))
        .order_by(LookupItem.position.asc(), LookupItem.value.asc())
        .all()
    ]
    used_councils = [
        c
        for (c,) in db.query(distinct(SiteCouncil.council_name)).order_by(SiteCouncil.council_name).all()
        if c
    ]
    councils = list(dict.fromkeys([*lookup_councils, *used_councils]))
    roads = [
        r.value
        for r in db.query(LookupItem)
        .filter(LookupItem.kind == "road", LookupItem.active.is_(True))
        .order_by(LookupItem.position.asc(), LookupItem.value.asc())
        .all()
    ]
    return {
        "workflow_stages": stage_meta(db),
        "doc_categories": DOC_CATEGORIES,
        "priority_threshold_days": rules.priority_must_have_days,
        "priority_must_have_days": rules.priority_must_have_days,
        "must_have_offset_business_days": rules.must_have_offset_business_days,
        "council_no_objection_business_days": rules.council_no_objection_business_days,
        "moa_wait_sla_business_days": rules.moa_wait_sla_business_days,
        "financial_years": fy_choices(),
        "programs": programs,
        "councils": councils,
        "roads": roads,
        "rules": rules.as_dict(),
    }


def _page(name: str) -> FileResponse:
    path = STATIC_DIR / name
    if not path.exists():
        path = STATIC_DIR / "index.html"
    return FileResponse(path)


@app.get("/")
def index():
    return _page("index.html")


@app.get("/dashboard")
def dashboard_page():
    return _page("dashboard.html")


@app.get("/tracking")
def tracking_page():
    return _page("tracking.html")


@app.get("/lists")
def lists_page():
    return _page("lists.html")


@app.get("/stages")
def stages_page():
    return _page("stages.html")


@app.get("/settings")
def settings_page():
    return _page("settings.html")


@app.get("/archive")
def archive_page():
    return _page("archive.html")


@app.get("/map")
def map_page():
    return _page("map.html")


@app.get("/documents")
def documents_page():
    return _page("documents.html")


@app.get("/costs")
def costs_page():
    return _page("costs.html")


@app.get("/rates")
def rates_page():
    return _page("rates.html")


@app.get("/system")
def system_page():
    return _page("system.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
