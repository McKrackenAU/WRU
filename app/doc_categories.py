"""Admin-configurable document types, seeded from the built-in list."""

from __future__ import annotations

import re

from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import DOC_CATEGORIES, DOC_CATEGORY_LABELS, Document, DocumentCategoryDef

FALLBACK_KEY = "other"

DEFAULT_DOC_CATEGORIES: list[dict] = [
    {"key": "email", "label": "Email", "position": 10, "protected": False},
    {"key": "tgs", "label": "TGS", "position": 20, "protected": False},
    {"key": "plan", "label": "Plan", "position": 30, "protected": False},
    {"key": "moa", "label": "MoA", "position": 40, "protected": False},
    {"key": "correspondence", "label": "Correspondence", "position": 50, "protected": False},
    {"key": "scoping", "label": "Scoping", "position": 55, "protected": False},
    {"key": "photo", "label": "Photo", "position": 60, "protected": False},
    {"key": "other", "label": "Other", "position": 70, "protected": True},
]


def slug_category_key(label: str) -> str:
    key = re.sub(r"[^a-zA-Z0-9]+", "_", (label or "").strip().lower()).strip("_")
    return (key[:64] or "type")


def ensure_doc_category_seed(db: Session) -> None:
    existing = {r.key: r for r in db.query(DocumentCategoryDef).all()}
    changed = False
    for row in DEFAULT_DOC_CATEGORIES:
        found = existing.get(row["key"])
        if found:
            if row.get("protected") and not found.protected:
                found.protected = True
                changed = True
            continue
        db.add(
            DocumentCategoryDef(
                key=row["key"],
                label=row["label"],
                position=row["position"],
                active=True,
                protected=bool(row.get("protected")),
            )
        )
        changed = True
    if FALLBACK_KEY not in existing and FALLBACK_KEY not in {r["key"] for r in DEFAULT_DOC_CATEGORIES}:
        db.add(
            DocumentCategoryDef(
                key=FALLBACK_KEY,
                label="Other",
                position=999,
                active=True,
                protected=True,
            )
        )
        changed = True
    if changed:
        db.commit()


def all_doc_categories(db: Session) -> list[DocumentCategoryDef]:
    ensure_doc_category_seed(db)
    return (
        db.query(DocumentCategoryDef)
        .order_by(DocumentCategoryDef.position.asc(), DocumentCategoryDef.id.asc())
        .all()
    )


def active_doc_categories(db: Session) -> list[DocumentCategoryDef]:
    return [r for r in all_doc_categories(db) if r.active]


def active_category_keys(db: Session | None = None) -> list[str]:
    if db is None:
        return list(DOC_CATEGORIES)
    return [r.key for r in active_doc_categories(db)]


def category_label_map(db: Session | None = None) -> dict[str, str]:
    if db is None:
        return dict(DOC_CATEGORY_LABELS)
    return {r.key: r.label for r in all_doc_categories(db)}


def category_meta(db: Session) -> list[dict]:
    return [{"key": r.key, "label": r.label} for r in active_doc_categories(db)]


def usage_count(db: Session, key: str) -> int:
    return (
        db.query(func.count(Document.id))
        .filter(Document.category == key)
        .scalar()
        or 0
    )


def reassign_documents(db: Session, from_key: str, to_key: str) -> int:
    if from_key == to_key:
        return 0
    n = (
        db.query(Document)
        .filter(Document.category == from_key)
        .update({Document.category: to_key}, synchronize_session=False)
    )
    return int(n or 0)
