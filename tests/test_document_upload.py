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
DOCS_HTML = (ROOT / "app/static/documents.html").read_text(encoding="utf-8")
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
    assert "compress_document" in DOCS_PY
    assert "read_document_bytes" in DOCS_PY
    assert "stored_encoding" in DOCS_PY
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
    assert "compresses files when that saves space" in INDEX
    assert "downloadDocumentsZip" in APP_JS
    assert 'id="docSelectAll"' in INDEX
    assert 'id="btnDownloadDocs"' in INDEX
    assert 'id="btnDownloadAllDocs"' in INDEX
    assert "Download all as folder" in INDEX


    assert "downloadDocumentsZip" in DOCS_JS
    assert 'id="btnDownloadAll"' in DOCS_HTML
    assert "Download all as folder" in DOCS_HTML
    assert "downloadChunkedSession" in COMMON
    assert "zip/session" in COMMON
    assert "download-session" in COMMON
    assert "wrap_chunk_payload" in DOCS_PY
    assert "begin_documents_zip_session" in DOCS_PY
    assert 'html.dark .doc-pick input[type="checkbox"]:checked' in (
        ROOT / "app/static/css/style.css"
    ).read_text(encoding="utf-8")


def test_xor_chunks_roundtrip_for_zip_and_pdf_magic():
    import base64

    from app.routers.documents import wrap_chunk_payload

    key = b"K" * 32
    key_b64 = base64.b64encode(key).decode("ascii")
    zip_data = b"PK\x03\x04" + bytes(range(64))
    encoded = wrap_chunk_payload(zip_data, key_b64)
    assert not base64.b64decode(encoded).startswith(b"PK")
    assert unwrap_chunk_payload(encoded, key_b64) == zip_data

    pdf = b"%PDF-1.4" + bytes(range(64))
    wrapped = xor_repeat(pdf, key)
    assert not wrapped.startswith(b"%PDF")
    encoded = base64.b64encode(wrapped).decode("ascii")
    assert unwrap_chunk_payload(encoded, key_b64) == pdf
    assert CHUNK_SIZE == 48 * 1024
