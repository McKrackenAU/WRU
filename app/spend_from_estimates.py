"""Seed / refresh site-level actual spend from saved cost estimates."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .models import ActualSpend, AsphaltEstimate, CostEstimate

SOURCE_FROM_ESTIMATE = "from_estimate"


def traffic_estimate_total(estimate: CostEstimate) -> float | None:
    if estimate.summary_total is not None:
        return float(estimate.summary_total)
    results = estimate.results or {}
    if estimate.mode == "standard":
        total = results.get("site_traffic_total")
        return float(total) if total is not None else None
    a = (results.get("option_3x8") or {}).get("grand_total")
    b = (results.get("option_2x12") or {}).get("grand_total")
    vals = [float(v) for v in (a, b) if v is not None]
    return min(vals) if vals else None


def asphalt_estimate_total(estimate: AsphaltEstimate) -> float | None:
    if estimate.summary_total is not None:
        return float(estimate.summary_total)
    total = (estimate.results or {}).get("total")
    return float(total) if total is not None else None


def upsert_spend_from_estimate(
    db: Session,
    *,
    kind: str,
    site_id: int,
    amount: float | None,
    estimate_id: int,
    estimate_name: str,
    asphalt_subcontractor_id: int | None = None,
    created_by: str | None = None,
) -> tuple[ActualSpend | None, str]:
    """Create or refresh the site+kind seed spend row from an estimate.

    Only touches rows with source=from_estimate. Manual / calculated rows are left alone.
    """
    if amount is None:
        return None, "skipped_no_amount"
    amount = round(float(amount), 2)
    name = (estimate_name or "Estimate").strip() or "Estimate"
    inputs: dict[str, Any] = {
        "estimate_id": estimate_id,
        "estimate_name": name,
        "kind": kind,
    }
    results: dict[str, Any] = {"summary_total": amount}

    existing = (
        db.query(ActualSpend)
        .filter(
            ActualSpend.site_id == site_id,
            ActualSpend.kind == kind,
            ActualSpend.source == SOURCE_FROM_ESTIMATE,
        )
        .order_by(ActualSpend.id.desc())
        .first()
    )
    if existing:
        existing.amount = amount
        existing.inputs = inputs
        existing.results = results
        existing.category = existing.category or "Estimate"
        existing.notes = f"From estimate: {name}"
        if kind == "asphalt":
            existing.asphalt_subcontractor_id = asphalt_subcontractor_id
        else:
            existing.asphalt_subcontractor_id = None
        return existing, "updated"

    # Don't recreate a seed if the site already has user-entered spend for this kind
    other = (
        db.query(ActualSpend)
        .filter(ActualSpend.site_id == site_id, ActualSpend.kind == kind)
        .first()
    )
    if other:
        return None, "skipped_user_owned"

    row = ActualSpend(
        kind=kind,
        site_id=site_id,
        work_date=None,
        amount=amount,
        source=SOURCE_FROM_ESTIMATE,
        category="Estimate",
        asphalt_subcontractor_id=asphalt_subcontractor_id if kind == "asphalt" else None,
        notes=f"From estimate: {name}",
        inputs=inputs,
        results=results,
        created_by=(created_by or "").strip() or None,
    )
    db.add(row)
    return row, "created"


def sync_spend_from_estimates(
    db: Session,
    *,
    site_id: int | None = None,
) -> dict[str, int]:
    """Upsert from_estimate spend rows from each site's latest traffic/asphalt estimate."""
    counts = {"created": 0, "updated": 0, "skipped": 0}

    traffic_q = db.query(CostEstimate).filter(CostEstimate.site_id.isnot(None))
    if site_id is not None:
        traffic_q = traffic_q.filter(CostEstimate.site_id == site_id)
    traffic_rows = traffic_q.order_by(CostEstimate.created_at.desc(), CostEstimate.id.desc()).all()
    seen_traffic: set[int] = set()
    for est in traffic_rows:
        sid = int(est.site_id)
        if sid in seen_traffic:
            continue
        seen_traffic.add(sid)
        _, action = upsert_spend_from_estimate(
            db,
            kind="traffic",
            site_id=sid,
            amount=traffic_estimate_total(est),
            estimate_id=est.id,
            estimate_name=est.name,
            created_by=est.created_by,
        )
        if action.startswith("skipped"):
            counts["skipped"] += 1
        else:
            counts[action] += 1

    asphalt_q = db.query(AsphaltEstimate)
    if site_id is not None:
        asphalt_q = asphalt_q.filter(AsphaltEstimate.site_id == site_id)
    asphalt_rows = asphalt_q.order_by(AsphaltEstimate.created_at.desc(), AsphaltEstimate.id.desc()).all()
    seen_asphalt: set[int] = set()
    for est in asphalt_rows:
        sid = int(est.site_id)
        if sid in seen_asphalt:
            continue
        seen_asphalt.add(sid)
        _, action = upsert_spend_from_estimate(
            db,
            kind="asphalt",
            site_id=sid,
            amount=asphalt_estimate_total(est),
            estimate_id=est.id,
            estimate_name=est.name,
            asphalt_subcontractor_id=est.subcontractor_id,
            created_by=est.created_by,
        )
        if action.startswith("skipped"):
            counts["skipped"] += 1
        else:
            counts[action] += 1

    db.commit()
    return counts
