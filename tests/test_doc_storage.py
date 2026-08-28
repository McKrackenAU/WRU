"""Document compression and live/archive disk paths."""

from __future__ import annotations

from types import SimpleNamespace

from app.storage import (
    compress_document,
    candidate_document_paths,
    decode_stored_bytes,
    relocate_site_files,
    resolve_stored_path,
    unlink_stored_file,
)


def test_gzip_text_roundtrip():
    original = (b"hello world " * 80) + b"email body\n"
    blob = compress_document(original, "note.txt", "text/plain")
    assert blob.encoding == "gzip"
    assert blob.logical_size == len(original)
    assert blob.stored_size < blob.logical_size
    assert decode_stored_bytes(blob.data, blob.encoding) == original


def test_skip_gzip_for_jpeg_magic_and_suffix():
    data = b"\xff\xd8" + b"\x00" * 2000
    blob = compress_document(data, "photo.jpg", "image/jpeg")
    assert blob.encoding == "plain"
    assert blob.data == data


def test_skip_gzip_for_zip_magic():
    data = b"PK\x03\x04" + b"x" * 2000
    blob = compress_document(data, "pack.bin", "application/octet-stream")
    assert blob.encoding == "plain"


def test_png_optimize_keeps_or_shrinks(tmp_path):
    from PIL import Image

    im = Image.new("RGB", (80, 80), (12, 80, 200))
    src = tmp_path / "a.png"
    im.save(src, format="PNG")
    raw = src.read_bytes()
    blob = compress_document(raw, "a.png", "image/png")
    restored = decode_stored_bytes(blob.data, blob.encoding)
    assert blob.logical_size <= len(raw)
    assert restored  # still a PNG (or gzipped PNG logical)
    assert blob.encoding == "plain"  # png suffix skips gzip


def test_tiny_files_stay_plain():
    blob = compress_document(b"short", "tiny.txt", "text/plain")
    assert blob.encoding == "plain"
    assert blob.data == b"short"


def test_candidate_paths_reject_traversal(tmp_path, monkeypatch):
    live = tmp_path / "uploads"
    arch = tmp_path / "archive"
    live.mkdir()
    arch.mkdir()
    monkeypatch.setattr("app.storage.UPLOAD_DIR", live)
    monkeypatch.setattr("app.storage.ARCHIVE_DIR", arch)
    assert candidate_document_paths("../secret") == []
    assert candidate_document_paths("a/b.pdf") == []
    assert candidate_document_paths("") == []
    paths = candidate_document_paths("12_abc.pdf")
    assert paths == [live / "12_abc.pdf", arch / "12_abc.pdf"]


def test_resolve_prefers_live_then_archive(tmp_path, monkeypatch):
    live = tmp_path / "uploads"
    arch = tmp_path / "archive"
    live.mkdir()
    arch.mkdir()
    monkeypatch.setattr("app.storage.UPLOAD_DIR", live)
    monkeypatch.setattr("app.storage.ARCHIVE_DIR", arch)
    (arch / "doc.txt").write_text("from-archive")
    path = resolve_stored_path("doc.txt")
    assert path == arch / "doc.txt"
    (live / "doc.txt").write_text("from-live")
    path = resolve_stored_path("doc.txt")
    assert path == live / "doc.txt"
    path = resolve_stored_path("doc.txt", prefer_archive=True)
    assert path == arch / "doc.txt"


def test_relocate_moves_docs_and_cost_attachments(tmp_path, monkeypatch):
    live = tmp_path / "uploads"
    arch = tmp_path / "archive"
    (live / "cost-estimates").mkdir(parents=True)
    arch.mkdir()
    monkeypatch.setattr("app.storage.UPLOAD_DIR", live)
    monkeypatch.setattr("app.storage.ARCHIVE_DIR", arch)

    doc_name = "9_abc.txt"
    att_name = "est1_quote.txt"
    (live / doc_name).write_text("plan")
    (live / "cost-estimates" / att_name).write_text("quote")

    db = SimpleNamespace()

    def query(model):
        name = getattr(model, "__name__", str(model))
        q = SimpleNamespace()
        if name == "Document":
            q.filter = lambda *a, **k: SimpleNamespace(
                all=lambda: [SimpleNamespace(stored_name=doc_name)]
            )
        elif name == "CostEstimate":
            q.filter = lambda *a, **k: SimpleNamespace(all=lambda: [SimpleNamespace(id=1)])
        else:
            q.filter = lambda *a, **k: SimpleNamespace(
                all=lambda: [SimpleNamespace(stored_name=att_name)]
            )
        return q

    db.query = query
    relocate_site_files(db, 9, archived=True)
    assert not (live / doc_name).exists()
    assert (arch / doc_name).read_text() == "plan"
    assert not (live / "cost-estimates" / att_name).exists()
    assert (arch / "cost-estimates" / att_name).read_text() == "quote"

    relocate_site_files(db, 9, archived=False)
    assert (live / doc_name).read_text() == "plan"
    assert not (arch / doc_name).exists()


def test_unlink_clears_live_and_archive(tmp_path, monkeypatch):
    live = tmp_path / "uploads"
    arch = tmp_path / "archive"
    live.mkdir()
    arch.mkdir()
    monkeypatch.setattr("app.storage.UPLOAD_DIR", live)
    monkeypatch.setattr("app.storage.ARCHIVE_DIR", arch)
    (live / "gone.pdf").write_text("a")
    (arch / "gone.pdf").write_text("b")
    unlink_stored_file("gone.pdf")
    assert not (live / "gone.pdf").exists()
    assert not (arch / "gone.pdf").exists()


def test_install_keeps_hdd_paths():
    from pathlib import Path

    script = (Path(__file__).resolve().parent.parent / "install/wru-install.sh").read_text(encoding="utf-8")
    assert "EXISTING_UPLOAD_DIR" in script
    assert "EXISTING_ARCHIVE_DIR" in script
    assert "WRU_UPLOAD_DIR=${WRU_UPLOAD_DIR@Q}" in script
    assert "WRU_ARCHIVE_DIR=${WRU_ARCHIVE_DIR@Q}" in script
