"""Chunked tracker upload helpers (Cloudflare / file-policy workaround)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.routers.import_tracker import (
    CHUNK_SIZE,
    assemble_chunks,
    _filename_ok,
    _looks_like_workbook,
)
from app.upload_limits import MULTIPART_MAX_BYTES, configure_multipart_limits
from starlette.formparsers import MultiPartParser


def test_multipart_part_limit_is_raised():
    configure_multipart_limits()
    assert MultiPartParser.max_part_size >= MULTIPART_MAX_BYTES
    assert MultiPartParser.max_part_size > 1024 * 1024


def test_chunk_size_is_well_under_one_megabyte():
    assert CHUNK_SIZE == 256 * 1024
    assert CHUNK_SIZE < 1024 * 1024


def test_assemble_chunks_roundtrip(tmp_path: Path):
    (tmp_path / "chunk-00000.bin").write_bytes(b"hello ")
    (tmp_path / "chunk-00001.bin").write_bytes(b"world")
    assert assemble_chunks(tmp_path, 11) == b"hello world"


def test_assemble_chunks_rejects_size_mismatch(tmp_path: Path):
    (tmp_path / "chunk-00000.bin").write_bytes(b"abc")
    with pytest.raises(HTTPException) as exc:
        assemble_chunks(tmp_path, 99)
    assert exc.value.status_code == 400


def test_workbook_magic_and_names():
    assert _looks_like_workbook(b"PK\x03\x04....")
    assert not _looks_like_workbook(b"\xd0\xcf\x11\xe0")
    assert _filename_ok("WRU Traffic TGS-MOA Tracker_V6 WIP.xlsm")
    assert _filename_ok("tracker.xlsx")
    assert not _filename_ok("tracker.xls")


def test_dry_run_from_real_v6_bytes():
    path = Path("/home/ubuntu/.cursor/projects/workspace/uploads/WRU_Traffic_TGS-MOA_Tracker_V6_WIP_f68a.xlsm")
    if not path.is_file():
        return
    from unittest.mock import MagicMock

    from app.routers.import_tracker import CHUNK_SIZE, run_tracker_import

    content = path.read_bytes()
    assert len(content) > CHUNK_SIZE
    result = run_tracker_import(
        MagicMock(),
        content,
        filename="WRU_Traffic_TGS-MOA_Tracker_V6_WIP.xlsm",
        update_existing=True,
        dry_run=True,
    )
    assert result["dry_run"] is True
    assert result["parsed"] >= 60
