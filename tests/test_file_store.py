"""Uploaded files are compressed on disk and restored on download."""

from pathlib import Path

from app.file_store import (
    MAGIC,
    compress_bytes,
    decompress_bytes,
    is_wrapped,
    materialize_original,
    read_stored_bytes,
    write_stored_bytes,
)

DOCS_PY = (Path(__file__).resolve().parent.parent / "app/routers/documents.py").read_text(
    encoding="utf-8"
)
COSTS_PY = (Path(__file__).resolve().parent.parent / "app/routers/costs.py").read_text(
    encoding="utf-8"
)


def test_gzip_wrapper_roundtrip_and_leaves_raw_alone():
    original = b"%PDF-1.4 notice letter " + (b"x" * 4000)
    packed = compress_bytes(original)
    assert packed.startswith(MAGIC)
    assert is_wrapped(packed)
    assert packed != original
    assert len(packed) < len(original)
    assert decompress_bytes(packed) == original
    assert decompress_bytes(original) == original


def test_write_and_read_restore_original(tmp_path):
    dest = tmp_path / "letter.pdf"
    payload = b"Works notification - Whitehall St\n" * 80
    stored_size, encoding = write_stored_bytes(dest, payload)
    on_disk = dest.read_bytes()
    assert encoding == "gzip"
    assert stored_size == len(on_disk)
    assert on_disk.startswith(MAGIC)
    assert on_disk != payload
    assert read_stored_bytes(dest) == payload
    unpacked, ephemeral = materialize_original(dest)
    try:
        assert ephemeral
        assert unpacked.read_bytes() == payload
    finally:
        if ephemeral:
            unpacked.unlink(missing_ok=True)


def test_document_and_cost_paths_use_file_store():
    assert "write_stored_bytes" in DOCS_PY
    assert "read_stored_bytes" in DOCS_PY
    assert "materialize_original" in DOCS_PY
    assert "write_stored_bytes" in COSTS_PY
    assert "materialize_original" in COSTS_PY
