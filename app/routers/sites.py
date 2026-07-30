from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..financial_year import australian_financial_year
from ..models import MapFeature, MapLayer, Site, SiteCouncil
from ..schemas import SiteArchiveRequest, SiteCreate, SiteOut, SiteUpdate
from ..services import (
    apply_generic_moa_link,
    apply_workflow,
    ensure_workflow_steps,
    infer_financial_year,
    set_councils,
    site_to_dict,
)

router = APIRouter(prefix="/api/sites", tags=["sites"])


def _base_query(db: Session, *, archived: bool | None):
    query = db.query(Site)
    if archived is None:
        return query
    return query.filter(Site.archived.is_(archived))


def _attach_geometry(db: Session, site: Site, geometry: dict | None, name: str | None = None) -> None:
    if not geometry or not isinstance(geometry, dict) or "type" not in geometry:
        return
    fy = site.financial_year or australian_financial_year()
    layer = (
        db.query(MapLayer)
        .filter(MapLayer.financial_year == fy, MapLayer.name == "Site markups")
        .first()
    )
    if not layer:
        layer = MapLayer(
            name="Site markups",
            financial_year=fy,
            original_filename="site-markups.geojson",
            stored_name=f"site_markups_{fy}.geojson",
            feature_count=0,
            uploaded_by="system",
        )
        db.add(layer)
        db.flush()
    # Replace existing markup features for this site on this layer
    for feat in list(site.map_features or []):
        if feat.layer_id == layer.id:
            db.delete(feat)
    feat = MapFeature(
        layer_id=layer.id,
        site_id=site.id,
        name=name or site.road_name,
        description=site.site_number,
        geometry=geometry,
        properties={"source": "site_register", "site_id": site.id},
    )
    db.add(feat)
    db.flush()
    layer.feature_count = db.query(MapFeature).filter(MapFeature.layer_id == layer.id).count()


@router.get("", response_model=list[SiteOut])
def list_sites(
    q: str | None = Query(default=None),
    priority: int | None = Query(default=None, ge=1, le=2),
    stage: str | None = Query(default=None),
    council: str | None = Query(default=None),
    program: str | None = Query(default=None),
    financial_year: str | None = Query(default=None),
    permits_priority: bool | None = Query(default=None),
    trims_priority: bool | None = Query(default=None),
    client_list: str | None = Query(default=None),
    generic_moa: bool | None = Query(default=None),
    archived: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    query = _base_query(db, archived=archived)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Site.road_name.ilike(like),
                Site.site_number.ilike(like),
                Site.moa_number.ilike(like),
                Site.comments.ilike(like),
                Site.tgs_reference.ilike(like),
                Site.program.ilike(like),
            )
        )
    if program:
        query = query.filter(Site.program.ilike(program.strip()))
    if financial_year:
        query = query.filter(
            or_(
                Site.financial_year == financial_year,
                Site.archived_fy == financial_year,
            )
        )
    if council:
        query = query.join(SiteCouncil).filter(SiteCouncil.council_name.ilike(council.strip()))
    if generic_moa is not None:
        query = query.filter(Site.is_generic_moa.is_(generic_moa))

    sites = query.order_by(Site.indicative_site_start_date.asc().nullslast(), Site.id.asc()).all()
    results = [site_to_dict(site, db=db) for site in sites]

    if priority is not None:
        results = [row for row in results if row["today_priority"] == priority]
    if stage:
        results = [
            row
            for row in results
            if row["metrics"].get("current_stage") == stage
            or any(w["stage"] == stage and w["completed"] for w in row["workflow"])
        ]
    if permits_priority is not None:
        results = [
            row
            for row in results
            if bool(row["metrics"].get("on_permits_priority_list")) == permits_priority
        ]
    if trims_priority is not None:
        results = [
            row
            for row in results
            if bool(row["metrics"].get("on_trims_priority_list")) == trims_priority
        ]
    if client_list:
        results = [row for row in results if row["metrics"].get("client_list") == client_list]
    if permits_priority or trims_priority or client_list in ("permits", "trims"):
        results.sort(key=lambda r: r["metrics"].get("permits_priority_rank", 999999))
    return results


@router.get("/generic-moas", response_model=list[SiteOut])
def list_generic_moas(db: Session = Depends(get_db)):
    sites = (
        db.query(Site)
        .filter(Site.archived.is_(False), Site.is_generic_moa.is_(True))
        .order_by(Site.moa_number.asc().nullslast(), Site.id.asc())
        .all()
    )
    return [site_to_dict(s, db=db) for s in sites]


@router.post("", response_model=SiteOut, status_code=201)
def create_site(payload: SiteCreate, db: Session = Depends(get_db)):
    site = Site(
        road_name=payload.road_name.strip(),
        site_number=payload.site_number.strip(),
        program=(payload.program or "").strip() or None,
        tgs_reference=(payload.tgs_reference or "").strip() or None,
        indicative_site_start_date=payload.indicative_site_start_date,
        moa_must_have_received_date=payload.moa_must_have_received_date,
        comments=payload.comments,
        moa_number=payload.moa_number,
        moa_submission_date=payload.moa_submission_date,
        is_generic_moa=bool(payload.is_generic_moa),
        financial_year=payload.financial_year or None,
        custom_fields=payload.custom_fields or {},
        archived=False,
    )
    db.add(site)
    db.flush()
    ensure_workflow_steps(site, db)
    apply_workflow(site, payload.workflow, db)
    set_councils(site, payload.councils)
    if payload.linked_generic_moa_id:
        generic = db.get(Site, payload.linked_generic_moa_id)
        if not generic:
            raise HTTPException(status_code=404, detail="Generic MoA not found")
        try:
            apply_generic_moa_link(site, generic, db)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not site.financial_year:
        site.financial_year = infer_financial_year(site)
    _attach_geometry(db, site, payload.geometry, payload.geometry_name)
    db.commit()
    db.refresh(site)
    return site_to_dict(site, db=db)


@router.get("/{site_id}", response_model=SiteOut)
def get_site(site_id: int, db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site_to_dict(site, db=db)


@router.patch("/{site_id}", response_model=SiteOut)
def update_site(site_id: int, payload: SiteUpdate, db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    data = payload.model_dump(exclude_unset=True)
    workflow = data.pop("workflow", None)
    custom_fields = data.pop("custom_fields", None)
    councils = data.pop("councils", None)
    geometry = data.pop("geometry", None)
    geometry_name = data.pop("geometry_name", None)
    linked_id = data.pop("linked_generic_moa_id", None) if "linked_generic_moa_id" in data else ...

    for key, value in data.items():
        if isinstance(value, str):
            value = value.strip() or None
        setattr(site, key, value)

    if custom_fields is not None:
        merged = dict(site.custom_fields or {})
        merged.update(custom_fields)
        site.custom_fields = merged

    set_councils(site, councils)
    apply_workflow(site, workflow, db)

    if linked_id is not ...:
        if linked_id is None:
            site.linked_generic_moa_id = None
        else:
            generic = db.get(Site, linked_id)
            if not generic:
                raise HTTPException(status_code=404, detail="Generic MoA not found")
            try:
                apply_generic_moa_link(site, generic, db)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not site.financial_year:
        site.financial_year = infer_financial_year(site)
    if geometry is not None:
        _attach_geometry(db, site, geometry, geometry_name)
    db.commit()
    db.refresh(site)
    return site_to_dict(site, db=db)


@router.post("/{site_id}/archive", response_model=SiteOut)
def archive_site(
    site_id: int,
    payload: SiteArchiveRequest | None = None,
    db: Session = Depends(get_db),
):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    fy = (payload.financial_year if payload else None) or infer_financial_year(site)
    site.archived = True
    site.archived_at = datetime.now(timezone.utc)
    site.archived_fy = fy
    site.financial_year = site.financial_year or fy
    db.commit()
    db.refresh(site)
    return site_to_dict(site, db=db)


@router.post("/{site_id}/restore", response_model=SiteOut)
def restore_site(site_id: int, db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    site.archived = False
    site.archived_at = None
    site.archived_fy = None
    db.commit()
    db.refresh(site)
    return site_to_dict(site, db=db)


@router.delete("/{site_id}", status_code=204)
def delete_site_blocked(site_id: int):
    raise HTTPException(
        status_code=405,
        detail="Hard delete disabled — archive the site instead",
    )
