"""Admin-managed document types and bulk zip download wiring."""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.doc_categories import (
    FALLBACK_KEY,
    ensure_doc_category_seed,
    reassign_documents,
    slug_category_key,
    usage_count,
)
from app.models import Document, DocumentCategoryDef, Site
from app.routers.documents import normalize_doc_category

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_HTML = (ROOT / "app/static/settings.html").read_text(encoding="utf-8")
SETTINGS_JS = (ROOT / "app/static/js/settings.js").read_text(encoding="utf-8")
INDEX = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
COMMON = (ROOT / "app/static/js/common.js").read_text(encoding="utf-8")
DOCS_HTML = (ROOT / "app/static/documents.html").read_text(encoding="utf-8")
DOCS_JS = (ROOT / "app/static/js/documents.js").read_text(encoding="utf-8")
ADMIN_HTML = (ROOT / "app/static/admin.html").read_text(encoding="utf-8")
DOCS_PY = (ROOT / "app/routers/documents.py").read_text(encoding="utf-8")
ADMIN_PY = (ROOT / "app/routers/settings_admin.py").read_text(encoding="utf-8")


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _site(db):
    now = datetime.now(timezone.utc)
    site = Site(
        road_name="DYNON RD",
        site_number="S1",
        created_at=now,
        updated_at=now,
        custom_fields={},
    )
    db.add(site)
    db.flush()
    return site


def _doc(db, site, category="plan", name="a.pdf"):
    doc = Document(
        site_id=site.id,
        category=category,
        stored_name=f"{site.id}_{name}",
        original_filename=name,
        size_bytes=12,
    )
    db.add(doc)
    db.flush()
    return doc


def test_seed_creates_builtin_types():
    db = _session()
    ensure_doc_category_seed(db)
    rows = db.query(DocumentCategoryDef).all()
    keys = {r.key for r in rows}
    assert {"email", "tgs", "plan", "moa", "correspondence", "photo", "other"} <= keys
    other = next(r for r in rows if r.key == FALLBACK_KEY)
    assert other.protected is True


def test_slug_and_reassign():
    assert slug_category_key("SWMS Pack") == "swms_pack"
    db = _session()
    site = _site(db)
    _doc(db, site, "tgs", "one.pdf")
    _doc(db, site, "tgs", "two.pdf")
    db.commit()
    n = reassign_documents(db, "tgs", "other")
    db.commit()
    assert n == 2
    assert usage_count(db, "tgs") == 0
    assert usage_count(db, "other") == 2


def test_normalize_uses_allowed_set():
    assert normalize_doc_category("plan", "a.pdf") == "plan"
    assert normalize_doc_category("other", "note.eml") == "email"
    assert normalize_doc_category("SWMS", "x.bin", allowed={"swms", "other"}) == "swms"
    try:
        normalize_doc_category("nonesuch", "x.bin")
        raise AssertionError("expected invalid category")
    except HTTPException as exc:
        assert exc.status_code == 400


def test_admin_settings_lists_document_types():
    assert "<h2>Document types</h2>" in SETTINGS_HTML
    assert 'id="docTypeList"' in SETTINGS_HTML
    assert "btnAddDocType" in SETTINGS_JS
    assert "/api/admin/doc-categories" in SETTINGS_JS
    assert "create_doc_category" in ADMIN_PY
    assert "doc_category_defs" in (ROOT / "app/main.py").read_text(encoding="utf-8")


def test_drawer_and_library_have_selection_and_zip():
    assert 'id="docSelectAll"' in INDEX
    assert 'id="btnDownloadDocs"' in INDEX
    assert "downloadDocumentsZip" in APP_JS
    assert "downloadDocumentsZip" in DOCS_JS
    assert 'id="libSelectAll"' in DOCS_HTML
    assert 'id="btnDownloadSelected"' in DOCS_HTML
    assert "download_documents_zip" in DOCS_PY
    assert 'id="docSelectBar"' in INDEX
    assert "applyDocCategories" in COMMON
    assert "Backup &amp; migrate" in ADMIN_HTML or "Backup" in ADMIN_HTML
