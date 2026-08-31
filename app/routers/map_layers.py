from __future__ import annotations

import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..database import get_db
from ..storage_paths import kml_dir
from ..financial_year import australian_financial_year
from ..kml_parse import parse_kml_features
from ..map_config import get_nearmap_api_key, map_config_public, set_nearmap_api_key
from ..models import MapFeature, MapLayer, Site, User
from ..schemas import MapFeatureLink, MapFeatureOut, MapLayerOut
from ..services import lean_sites_query

router = APIRouter(prefix="/api/map", tags=["map"])

MAX_KML_BYTES = 50 * 1024 * 1024


def _kml_dir() -> Path:
    return kml_dir()


class NearmapKeyIn(BaseModel):
    api_key: str | None = Field(default=None, max_length=256)


@router.get("/config")
def map_basemap_config():
    """Basemap providers + Nearmap key for the works map (VenInspect-style client tiles)."""
    return map_config_public()


@router.put("/nearmap-key")
def put_nearmap_key(payload: NearmapKeyIn, _: User = Depends(require_admin)):
    """Save or clear the Nearmap API key (Admin → System)."""
    try:
        set_nearmap_api_key(payload.api_key)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    cfg = map_config_public()
    return {
        "ok": True,
        "nearmap_configured": cfg["nearmap_configured"],
        "nearmap_key_source": cfg["nearmap_key_source"],
        "masked_key": _mask_key(get_nearmap_api_key()),
    }


def _mask_key(key: str | None) -> str | None:
    if not key:
        return None
    if len(key) <= 8:
        return "••••••••"
    return f"{key[:4]}…{key[-4:]}"


def _feature_out(feat: MapFeature) -> dict:
    site_payload = None
    if feat.site:
        site_payload = {
            "id": feat.site.id,
            "road_name": feat.site.road_name,
            "site_number": feat.site.site_number,
            "moa_number": feat.site.moa_number,
            "tgs_reference": feat.site.tgs_reference,
            "financial_year": feat.site.archived_fy or feat.site.financial_year,
            "archived": feat.site.archived,
        }
    return {
        "id": feat.id,
        "layer_id": feat.layer_id,
        "site_id": feat.site_id,
        "name": feat.name,
        "description": feat.description,
        "geometry": feat.geometry,
        "properties": feat.properties or {},
        "financial_year": feat.layer.financial_year if feat.layer else None,
        "site": site_payload,
    }


@router.post("/parse-kml")
async def parse_kml(file: UploadFile = File(...)):
    """Parse a KML upload and return placemark geometries (for site register attach)."""
    content = await file.read()
    if len(content) > MAX_KML_BYTES:
        raise HTTPException(status_code=400, detail="KML too large")
    try:
        features = parse_kml_features(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not features:
        raise HTTPException(status_code=400, detail="No placemark geometries found in KML")
    return {
        "feature_count": len(features),
        "features": features,
        "primary_geometry": features[0]["geometry"],
        "primary_name": features[0].get("name"),
    }


@router.get("/layers", response_model=list[MapLayerOut])
def list_layers(financial_year: str | None = None, db: Session = Depends(get_db)):
    query = db.query(MapLayer)
    if financial_year:
        query = query.filter(MapLayer.financial_year == financial_year)
    return query.order_by(MapLayer.financial_year.desc(), MapLayer.id.desc()).all()


@router.post("/layers", response_model=MapLayerOut, status_code=201)
async def upload_kml(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    financial_year: str | None = Form(default=None),
    uploaded_by: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    original = Path(file.filename or "layer.kml").name
    if not original.lower().endswith((".kml", ".xml")):
        raise HTTPException(status_code=400, detail="Upload a .kml file")

    content = await file.read(MAX_KML_BYTES + 1)
    if len(content) > MAX_KML_BYTES:
        raise HTTPException(status_code=413, detail="KML exceeds 50 MB limit")

    try:
        features = parse_kml_features(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not features:
        raise HTTPException(status_code=400, detail="No placemarks with geometry found in KML")

    fy = (financial_year or "").strip() or australian_financial_year()
    stored = f"kml_{uuid.uuid4().hex}_{original}"
    dest = _kml_dir() / stored
    async with aiofiles.open(dest, "wb") as out:
        await out.write(content)

    layer = MapLayer(
        name=(name or original).strip(),
        financial_year=fy,
        original_filename=original,
        stored_name=stored,
        feature_count=len(features),
        uploaded_by=uploaded_by,
    )
    db.add(layer)
    db.flush()

    # Auto-link by exact MoA / site-number tokens (avoid short substring false positives)
    sites = lean_sites_query(db).filter(Site.archived.is_(False)).all()
    by_moa = {(s.moa_number or "").strip().upper(): s for s in sites if (s.moa_number or "").strip()}
    by_site_no = {
        (s.site_number or "").strip().upper(): s
        for s in sites
        if (s.site_number or "").strip() and len((s.site_number or "").strip()) >= 2
    }

    import re

    for feat in features:
        props = feat.get("properties") or {}
        hay = " ".join(
            [
                feat.get("name") or "",
                feat.get("description") or "",
                " ".join(str(v) for v in props.values()),
            ]
        ).upper()
        tokens = set(re.findall(r"[A-Z0-9][A-Z0-9._/-]{1,}", hay))
        linked = None
        for moa, site in by_moa.items():
            if moa and (moa in tokens or re.search(rf"(?<![A-Z0-9]){re.escape(moa)}(?![A-Z0-9])", hay)):
                linked = site
                break
        if linked is None:
            for sno, site in by_site_no.items():
                if sno and (sno in tokens or re.search(rf"(?<![A-Z0-9]){re.escape(sno)}(?![A-Z0-9])", hay)):
                    linked = site
                    break
        db.add(
            MapFeature(
                layer_id=layer.id,
                site_id=linked.id if linked else None,
                name=feat.get("name"),
                description=feat.get("description"),
                geometry=feat["geometry"],
                properties=props,
            )
        )

    db.commit()
    db.refresh(layer)
    return layer


@router.get("/features", response_model=list[MapFeatureOut])
def list_features(
    financial_year: str | None = Query(default=None),
    layer_id: int | None = Query(default=None),
    linked_only: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    query = db.query(MapFeature).join(MapLayer)
    if financial_year:
        query = query.filter(MapLayer.financial_year == financial_year)
    if layer_id:
        query = query.filter(MapFeature.layer_id == layer_id)
    if linked_only:
        query = query.filter(MapFeature.site_id.isnot(None))
    feats = query.order_by(MapLayer.financial_year.desc(), MapFeature.id.asc()).all()
    return [_feature_out(f) for f in feats]


@router.get("/geojson")
def geojson(
    financial_year: str | None = Query(default=None),
    layer_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    feats = list_features(
        financial_year=financial_year, layer_id=layer_id, linked_only=False, db=db
    )
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": f["id"],
                "geometry": f["geometry"],
                "properties": {
                    # KML props first; WRU link fields always win (never clobber site/feature_id)
                    **(f.get("properties") or {}),
                    "feature_id": f["id"],
                    "layer_id": f["layer_id"],
                    "name": f["name"] or (f.get("properties") or {}).get("name"),
                    "description": f["description"],
                    "financial_year": f["financial_year"],
                    "site_id": f["site_id"],
                    "site": f["site"],
                },
            }
            for f in feats
        ],
    }


@router.patch("/features/{feature_id}", response_model=MapFeatureOut)
def link_feature(feature_id: int, payload: MapFeatureLink, db: Session = Depends(get_db)):
    feat = db.get(MapFeature, feature_id)
    if not feat:
        raise HTTPException(status_code=404, detail="Feature not found")
    if payload.site_id is not None:
        site = db.get(Site, payload.site_id)
        if not site:
            raise HTTPException(status_code=404, detail="Site not found")
        feat.site_id = site.id
    else:
        feat.site_id = None
    db.commit()
    db.refresh(feat)
    return _feature_out(feat)


@router.delete("/layers/{layer_id}", status_code=204)
def delete_layer(layer_id: int, db: Session = Depends(get_db)):
    layer = db.get(MapLayer, layer_id)
    if not layer:
        raise HTTPException(status_code=404, detail="Layer not found")
    path = _kml_dir() / layer.stored_name
    path.unlink(missing_ok=True)
    db.delete(layer)
    db.commit()
    return None
