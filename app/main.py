from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .database import Base, engine
from .models import WORKFLOW_LABELS, WORKFLOW_STAGES
from .routers import columns, documents, sites, tracking
from .schemas import MetaOut

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="WRU TGS Tracker",
    description="Ventia-styled traffic guidance / MoA workflow tracker with custom columns, tracking, and documents.",
    version="1.0.0",
)

Base.metadata.create_all(bind=engine)

app.include_router(sites.router)
app.include_router(columns.router)
app.include_router(tracking.router)
app.include_router(documents.router)


@app.get("/api/meta", response_model=MetaOut)
def meta():
    return {
        "workflow_stages": [
            {"key": key, "label": WORKFLOW_LABELS[key]} for key in WORKFLOW_STAGES
        ],
        "priority_threshold_days": 21,
    }


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
