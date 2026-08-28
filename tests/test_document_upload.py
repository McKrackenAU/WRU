"""Document uploads: chunked JSON sessions, multi-file, category updates."""

from pathlib import Path

from fastapi import HTTPException

from app.routers.documents import normalize_doc_category
from app.routers.import_tracker import CHUNK_SIZE, unwrap_chunk_payload, xor_repeat
from app.schemas import DocumentUpdate

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
COMMON = (ROOT / "app/static/js/common.js").read_text(encoding="utf-8")
DOCS_JS = (ROOT / "app/static/js/documents.js").read_text(encoding="utf-8")
DOCS_PY = (ROOT / "app/routers/documents.py").read_text(encoding="utf-8")


def test_normalize_category_and_email_inference():
    assert normalize_doc_category("plan", "a.pdf") == "plan"
    assert normalize_doc_category("other", "note.eml") == "email"
    assert normalize_doc_category("OTHER", "photo.jpg") == "other"
    try:
        normalize_doc_category("nonesuch", "x.bin")
        raise AssertionError("expected invalid category")
    except HTTPException as exc:
        assert exc.status_code == 400


def test_document_update_schema():
    patch = DocumentUpdate(category="tgs")
    assert patch.category == "tgs"
    assert patch.description is None


def test_chunked_document_upload_is_wired():
    assert "uploadFileChunked" in COMMON
    assert "documents/session" in APP_JS
    assert 'id="docFile" multiple' in INDEX
    assert "docCategorySelectHtml" in APP_JS
    assert 'data-doc-cat' in APP_JS
    assert 'method: "PATCH"' in APP_JS
    assert "begin_document_session" in DOCS_PY
    assert "update_document" in DOCS_PY
    assert 'id="docUploadStatus"' in INDEX
    assert 'id="docDropzone"' in INDEX
    assert 'data-tab="documents"' in INDEX
    assert 'data-panel="documents"' in INDEX
    activity = INDEX.split('data-panel="activity"', 1)[1].split("</section>", 1)[0]
    assert "docDropzone" not in activity
    assert "wireDocDropzone" in APP_JS
    assert 'addEventListener("drop"' in APP_JS
    assert "Drop files here" in INDEX
    assert "downloadDocumentsZip" in APP_JS
    assert 'id="docSelectAll"' in INDEX
    assert 'id="btnDownloadDocs"' in INDEX


def test_library_page_can_change_category():
    assert "docCategorySelectHtml" in DOCS_JS
    assert 'method: "PATCH"' in DOCS_JS
    assert "data-doc-cat" in DOCS_JS


def test_xor_chunks_roundtrip_for_pdf_magic():
    import base64

    key = b"K" * 32
    data = b"%PDF-1.4" + bytes(range(64))
    wrapped = xor_repeat(data, key)
    assert not wrapped.startswith(b"%PDF")
    encoded = base64.b64encode(wrapped).decode("ascii")
    key_b64 = base64.b64encode(key).decode("ascii")
    assert unwrap_chunk_payload(encoded, key_b64) == data
    assert CHUNK_SIZE == 48 * 1024
