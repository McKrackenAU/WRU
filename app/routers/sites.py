from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..database import UPLOAD_DIR, get_db
from ..financial_year import australian_financial_year
from ..activity import actor_name, log_site_activity, log_stage_change, site_label, snapshot_stage
from ..live_hub import notify_from_request
from ..lookups import ensure_lookup_value
from ..models import CostEstimate, MapFeature, MapLayer, Site, SiteCouncil
from ..schemas import (
    SiteArchiveRequest,
    SiteBulkArchiveOut,
    SiteBulkArchiveRequest,
    SiteBulkPurgeOut,
    SiteBulkPurgeRequest,
    SiteCreate,
    SiteOut,
    SiteReorderOut,
    SiteReorderRequest,
    SiteUpdate,
)
from ..services import (
    apply_generic_moa_link,
    apply_workflow,
    ensure_workflow_steps,
    infer_financial_year,
    set_councils,
    site_to_dict,
    sync_computed_fields,
)

router = APIRouter(prefix="/api/sites", tags=["sites"])


def _base_query(db: Session, *, archived: bool | None):
    query = (
        db.query(Site)
        .options(
            selectinload(Site.councils),
            selectinload(Site.workflow_steps),
            selectinload(Site.documents),
            selectinload(Site.tracking_events),
            selectinload(Site.cost_estimates),
        )
    )
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


def _site_file_paths(site: Site) -> list[Path]:
    """Local files that must be removed when a site is permanently purged."""
    paths: list[Path] = []
    for doc in site.documents or []:
        name = (getattr(doc, "stored_name", None) or "").strip()
        if name:
            paths.append(UPLOAD_DIR / name)
    for est in site.cost_estimates or []:
        for att in getattr(est, "attachments", None) or []:
            name = (getattr(att, "stored_name", None) or "").strip()
            if name:
                paths.append(UPLOAD_DIR / "cost-estimates" / name)
    return paths


def require_archived_for_purge(site: Site | None) -> Site:
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    if not site.archived:
        raise HTTPException(
            status_code=409,
            detail="Hard delete is only allowed from the archive — archive the site first",
        )
    return site


def _purge_query(db: Session):
    return db.query(Site).options(
        selectinload(Site.documents),
        selectinload(Site.cost_estimates).selectinload(CostEstimate.attachments),
    )


def purge_archived_sites(db: Session, sites: list[Site]) -> list[int]:
    """Permanently delete archived sites and their on-disk attachments."""
    files: list[Path] = []
    ids: list[int] = []
    for site in sites:
        require_archived_for_purge(site)
        files.extend(_site_file_paths(site))
        ids.append(int(site.id))
        db.delete(site)
    db.commit()
    for path in files:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    return ids


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

    sites = query.order_by(
        Site.register_order.asc().nullslast(),
        Site.indicative_site_start_date.asc().nullslast(),
        Site.id.asc(),
    ).all()
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


@router.post("/bulk-archive", response_model=SiteBulkArchiveOut)
def bulk_archive_sites(
    payload: SiteBulkArchiveRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    ids = sorted({int(i) for i in payload.site_ids if int(i) > 0})
    if not ids:
        raise HTTPException(status_code=400, detail="No site ids provided")
    sites = db.query(Site).filter(Site.id.in_(ids), Site.archived.is_(False)).all()
    if not sites:
        raise HTTPException(status_code=404, detail="No matching active sites found")
    now = datetime.now(timezone.utc)
    archived_ids: list[int] = []
    fy_used: str | None = (payload.financial_year or "").strip() or None
    for site in sites:
        fy = fy_used or infer_financial_year(site)
        site.archived = True
        site.archived_at = now
        site.archived_fy = fy
        site.financial_year = site.financial_year or fy
        archived_ids.append(site.id)
    db.commit()
    notify_from_request(request, site_ids=archived_ids, reason="archive")
    return SiteBulkArchiveOut(archived=len(archived_ids), site_ids=archived_ids, financial_year=fy_used)


@router.post("/bulk-purge", response_model=SiteBulkPurgeOut)
def bulk_purge_sites(
    payload: SiteBulkPurgeRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    ids = sorted({int(i) for i in payload.site_ids if int(i) > 0})
    if not ids:
        raise HTTPException(status_code=400, detail="No site ids provided")
    sites = _purge_query(db).filter(Site.id.in_(ids), Site.archived.is_(True)).all()
    if not sites:
        raise HTTPException(status_code=404, detail="No matching archived sites found")
    purged = purge_archived_sites(db, sites)
    notify_from_request(request, site_ids=purged, reason="purge")
    return SiteBulkPurgeOut(purged=len(purged), site_ids=purged)


def _program_key(value: str | None) -> str:
    return (value or "").strip() or "Unassigned"


def _program_filter(program: str | None):
    key = _program_key(program)
    if key == "Unassigned":
        return or_(Site.program.is_(None), Site.program == "", func.btrim(Site.program) == "")
    return func.lower(func.btrim(Site.program)) == key.lower()


@router.post("/reorder", response_model=SiteReorderOut)
def reorder_sites(
    payload: SiteReorderRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Persist register row order within a program (and move sites into that program if needed)."""
    target = _program_key(payload.program)
    ids = [int(i) for i in payload.site_ids if int(i) > 0]
    if not ids:
        raise HTTPException(status_code=400, detail="No site ids provided")
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=400, detail="Duplicate site ids in order list")

    sites = db.query(Site).filter(Site.id.in_(ids), Site.archived.is_(False)).all()
    by_id = {s.id: s for s in sites}
    if len(by_id) != len(ids):
        raise HTTPException(status_code=404, detail="One or more sites were not found")

    program_value = None if target == "Unassigned" else target
    for idx, site_id in enumerate(ids):
        site = by_id[site_id]
        site.program = program_value
        site.register_order = (idx + 1) * 10

    # Keep any other sites in this program after the reordered set, stable relative order
    others = (
        db.query(Site)
        .filter(Site.archived.is_(False), _program_filter(target), Site.id.notin_(ids))
        .order_by(Site.register_order.asc().nullslast(), Site.indicative_site_start_date.asc().nullslast(), Site.id.asc())
        .all()
    )
    base = len(ids) * 10
    for offset, site in enumerate(others, start=1):
        site.register_order = base + offset * 10

    db.commit()
    notify_from_request(request, site_ids=ids, reason="reorder")
    return SiteReorderOut(program=program_value, site_ids=ids)


@router.post("", response_model=SiteOut, status_code=201)
def create_site(payload: SiteCreate, request: Request, db: Session = Depends(get_db)):
    data = payload.model_dump(exclude={"councils", "workflow", "geometry", "geometry_name", "linked_generic_moa_id", "custom_fields"})
    for key in ("road_name", "site_number", "program", "tgs_reference", "moa_number", "extension_flag", "comments"):
        if isinstance(data.get(key), str):
            data[key] = data[key].strip() or None
    data["road_name"] = payload.road_name.strip()
    data["site_number"] = payload.site_number.strip()
    if data.get("register_order") is None:
        prog = data.get("program")
        max_ord = (
            db.query(func.max(Site.register_order))
            .filter(_program_filter(prog), Site.archived.is_(False))
            .scalar()
        )
        data["register_order"] = (max_ord or 0) + 10
    site = Site(**data, custom_fields=payload.custom_fields or {}, archived=False)
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
    sync_computed_fields(site, db)
    _attach_geometry(db, site, payload.geometry, payload.geometry_name)
    ensure_lookup_value(db, "road", site.road_name)
    db.commit()
    db.refresh(site)
    notify_from_request(request, site_ids=[site.id], reason="create")
    return site_to_dict(site, db=db)


@router.get("/{site_id}", response_model=SiteOut)
def get_site(site_id: int, db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site_to_dict(site, db=db)


@router.patch("/{site_id}", response_model=SiteOut)
def update_site(site_id: int, payload: SiteUpdate, request: Request, db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    if site.archived:
        raise HTTPException(
            status_code=400,
            detail="This site is archived — restore it before editing, or open it read-only from Archive.",
        )

    data = payload.model_dump(exclude_unset=True)
    workflow = data.pop("workflow", None)
    custom_fields = data.pop("custom_fields", None)
    councils = data.pop("councils", None)
    geometry = data.pop("geometry", None)
    geometry_name = data.pop("geometry_name", None)
    linked_id = data.pop("linked_generic_moa_id", None) if "linked_generic_moa_id" in data else ...

    before_stage = snapshot_stage(site, db)
    who = actor_name(request)

    for key, value in data.items():
        # Never blank out required identity fields during partial autosave
        if key in ("road_name", "site_number"):
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
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
    sync_computed_fields(site, db)
    if geometry is not None:
        _attach_geometry(db, site, geometry, geometry_name)
    ensure_lookup_value(db, "road", site.road_name)

    after_stage = snapshot_stage(site, db)
    if workflow is not None:
        log_stage_change(db, site, before_key=before_stage, after_key=after_stage, who=who)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Could not save site (database conflict — check council names are unique).",
        ) from exc
    db.refresh(site)
    notify_from_request(request, site_ids=[site.id], reason="update")
    return site_to_dict(site, db=db)


@router.post("/{site_id}/archive", response_model=SiteOut)
def archive_site(
    site_id: int,
    request: Request,
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
    who = actor_name(request)
    log_site_activity(
        db,
        site,
        event_type="archive",
        created_by=who,
        message=f"{who} archived {site_label(site)}",
    )
    db.commit()
    db.refresh(site)
    notify_from_request(request, site_ids=[site.id], reason="archive")
    return site_to_dict(site, db=db)


@router.post("/{site_id}/restore", response_model=SiteOut)
def restore_site(site_id: int, request: Request, db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    site.archived = False
    site.archived_at = None
    site.archived_fy = None
    who = actor_name(request)
    log_site_activity(
        db,
        site,
        event_type="restore",
        created_by=who,
        message=f"{who} restored {site_label(site)}",
    )
    db.commit()
    db.refresh(site)
    notify_from_request(request, site_ids=[site.id], reason="restore")
    return site_to_dict(site, db=db)


@router.delete("/{site_id}", status_code=204)
def delete_site(site_id: int, request: Request, db: Session = Depends(get_db)):
    site = _purge_query(db).filter(Site.id == site_id).first()
    require_archived_for_purge(site)
    purged = purge_archived_sites(db, [site])
    notify_from_request(request, site_ids=purged, reason="purge")
