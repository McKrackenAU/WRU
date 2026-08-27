"""Admin-managed lookup lists (roads, councils) and how they update sites."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from .models import LookupItem, Site, SiteCouncil


@dataclass
class LookupChange:
    row: LookupItem
    sites_updated: int
    merged: bool


def _usage_names(db: Session, kind: str) -> list[str]:
    if kind == "road":
        rows = db.query(distinct(Site.road_name)).filter(Site.road_name.isnot(None)).all()
    elif kind == "council":
        rows = db.query(distinct(SiteCouncil.council_name)).filter(SiteCouncil.council_name.isnot(None)).all()
    else:
        return []
    return [name.strip() for (name,) in rows if name and str(name).strip()]


def usage_counts(db: Session, kind: str) -> dict[str, int]:
    if kind == "road":
        rows = db.query(Site.road_name, func.count(Site.id)).group_by(Site.road_name).all()
    elif kind == "council":
        rows = (
            db.query(SiteCouncil.council_name, func.count(SiteCouncil.id))
            .group_by(SiteCouncil.council_name)
            .all()
        )
    else:
        return {}
    counts: dict[str, int] = {}
    for name, n in rows:
        if not name:
            continue
        key = name.strip().lower()
        counts[key] = counts.get(key, 0) + int(n)
    return counts


def sync_usage_into_lookups(db: Session, kind: str) -> int:
    """Ensure every road/council already used on a site appears in Admin lookups."""
    if kind not in {"road", "council"}:
        return 0
    names = _usage_names(db, kind)
    existing = {
        r.value.strip().lower(): r
        for r in db.query(LookupItem).filter(LookupItem.kind == kind).all()
    }
    max_pos = max((r.position for r in existing.values()), default=0)
    added = 0
    for name in names:
        key = name.lower()
        if key in existing:
            continue
        max_pos += 10
        row = LookupItem(kind=kind, value=name, position=max_pos, active=True)
        db.add(row)
        existing[key] = row
        added += 1
    if added:
        db.commit()
    return added


def ensure_lookup_value(db: Session, kind: str, value: str, *, commit: bool = False) -> LookupItem | None:
    name = (value or "").strip()
    if kind not in {"road", "council"} or not name:
        return None
    row = (
        db.query(LookupItem)
        .filter(LookupItem.kind == kind, LookupItem.value.ilike(name))
        .first()
    )
    if row:
        if not row.active:
            row.active = True
        return row
    max_pos = (
        db.query(func.max(LookupItem.position)).filter(LookupItem.kind == kind).scalar() or 0
    )
    row = LookupItem(kind=kind, value=name, position=max_pos + 10, active=True)
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    return row


def _propagate_rename(db: Session, kind: str, old_value: str, new_value: str) -> int:
    if not old_value or not new_value:
        return 0
    if old_value.strip().lower() == new_value.strip().lower() and old_value == new_value:
        return 0
    updated = 0
    if kind == "road":
        return (
            db.query(Site)
            .filter(Site.road_name.ilike(old_value))
            .update({Site.road_name: new_value}, synchronize_session="fetch")
        )
    if kind == "council":
        rows = db.query(SiteCouncil).filter(SiteCouncil.council_name.ilike(old_value)).all()
        for row in rows:
            clash = (
                db.query(SiteCouncil)
                .filter(
                    SiteCouncil.site_id == row.site_id,
                    SiteCouncil.id != row.id,
                    SiteCouncil.council_name.ilike(new_value),
                )
                .first()
            )
            if clash:
                db.delete(row)
            else:
                row.council_name = new_value
                updated += 1
        return updated
    return 0


def apply_lookup_update(
    db: Session,
    row: LookupItem,
    *,
    value: str,
    active: bool,
    position: int | None = None,
) -> LookupChange:
    new_value = value.strip()
    old_value = row.value
    sites_updated = 0
    merged = False
    target = row

    changed = new_value.lower() != old_value.strip().lower() or new_value != old_value
    if changed:
        other = (
            db.query(LookupItem)
            .filter(
                LookupItem.kind == row.kind,
                LookupItem.id != row.id,
                LookupItem.value.ilike(new_value),
            )
            .first()
        )
        dest = other.value if other else new_value
        sites_updated = _propagate_rename(db, row.kind, old_value, dest)
        if other:
            db.delete(row)
            other.active = True if active else other.active
            if position is not None:
                other.position = position
            target = other
            merged = True
        else:
            row.value = new_value

    if not merged:
        if position is not None:
            row.position = position
        row.active = active

    db.commit()
    db.refresh(target)
    return LookupChange(row=target, sites_updated=sites_updated, merged=merged)
