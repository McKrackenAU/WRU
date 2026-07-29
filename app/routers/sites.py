from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Site
from ..schemas import SiteCreate, SiteOut, SiteUpdate
from ..services import apply_workflow, ensure_workflow_steps, site_to_dict

router = APIRouter(prefix="/api/sites", tags=["sites"])


@router.get("", response_model=list[SiteOut])
def list_sites(
    q: str | None = Query(default=None, description="Search road name, site number, MoA, comments"),
    priority: int | None = Query(default=None, ge=1, le=2),
    db: Session = Depends(get_db),
):
    query = db.query(Site)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Site.road_name.ilike(like),
                Site.site_number.ilike(like),
                Site.moa_number.ilike(like),
                Site.comments.ilike(like),
            )
        )
    sites = query.order_by(Site.indicative_site_start_date.asc().nullslast(), Site.id.asc()).all()
    results = [site_to_dict(site) for site in sites]
    if priority is not None:
        results = [row for row in results if row["today_priority"] == priority]
    return results


@router.post("", response_model=SiteOut, status_code=201)
def create_site(payload: SiteCreate, db: Session = Depends(get_db)):
    site = Site(
        road_name=payload.road_name.strip(),
        site_number=payload.site_number.strip(),
        indicative_site_start_date=payload.indicative_site_start_date,
        moa_must_have_received_date=payload.moa_must_have_received_date,
        comments=payload.comments,
        moa_number=payload.moa_number,
        moa_submission_date=payload.moa_submission_date,
        custom_fields=payload.custom_fields or {},
    )
    db.add(site)
    db.flush()
    ensure_workflow_steps(site)
    apply_workflow(site, payload.workflow)
    db.commit()
    db.refresh(site)
    return site_to_dict(site)


@router.get("/{site_id}", response_model=SiteOut)
def get_site(site_id: int, db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site_to_dict(site)


@router.patch("/{site_id}", response_model=SiteOut)
def update_site(site_id: int, payload: SiteUpdate, db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    data = payload.model_dump(exclude_unset=True)
    workflow = data.pop("workflow", None)
    custom_fields = data.pop("custom_fields", None)

    for key, value in data.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(site, key, value)

    if custom_fields is not None:
        merged = dict(site.custom_fields or {})
        merged.update(custom_fields)
        site.custom_fields = merged

    apply_workflow(site, workflow)
    db.commit()
    db.refresh(site)
    return site_to_dict(site)


@router.delete("/{site_id}", status_code=204)
def delete_site(site_id: int, db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    db.delete(site)
    db.commit()
    return None
