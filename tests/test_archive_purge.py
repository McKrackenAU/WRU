"""Archive-only hard delete / purge guards."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.database import ARCHIVE_DIR, UPLOAD_DIR
from app.routers.sites import (
    _site_file_paths,
    purge_archived_sites,
    require_archived_for_purge,
)
from app.storage import candidate_document_paths


def test_purge_rejects_missing_site():
    with pytest.raises(HTTPException) as exc:
        require_archived_for_purge(None)
    assert exc.value.status_code == 404


def test_purge_rejects_active_site():
    site = SimpleNamespace(id=3, archived=False)
    with pytest.raises(HTTPException) as exc:
        require_archived_for_purge(site)
    assert exc.value.status_code == 409
    assert "archive" in str(exc.value.detail).lower()


def test_purge_allows_archived_site():
    site = SimpleNamespace(id=4, archived=True)
    assert require_archived_for_purge(site) is site


def test_site_file_paths_collects_documents_and_estimate_attachments():
    site = SimpleNamespace(
        documents=[SimpleNamespace(stored_name="12_abc.pdf"), SimpleNamespace(stored_name="  ")],
        cost_estimates=[
            SimpleNamespace(
                attachments=[SimpleNamespace(stored_name="quote.pdf")],
            )
        ],
    )
    paths = _site_file_paths(site)
    for expected in candidate_document_paths("12_abc.pdf"):
        assert expected in paths
    for expected in candidate_document_paths("quote.pdf", subdir="cost-estimates"):
        assert expected in paths
    assert UPLOAD_DIR / "12_abc.pdf" in paths
    if ARCHIVE_DIR.resolve() != UPLOAD_DIR.resolve():
        assert ARCHIVE_DIR / "12_abc.pdf" in paths


def test_purge_archived_sites_deletes_and_unlinks(tmp_path, monkeypatch):
    live = tmp_path / "uploads"
    arch = tmp_path / "archive"
    (arch / "cost-estimates").mkdir(parents=True)
    live.mkdir()
    doc = arch / "gone.pdf"
    att = arch / "cost-estimates" / "quote.pdf"
    doc.write_text("doc")
    att.write_text("att")
    leftover = live / "keep.pdf"
    leftover.write_text("keep")

    monkeypatch.setattr("app.storage.UPLOAD_DIR", live)
    monkeypatch.setattr("app.storage.ARCHIVE_DIR", arch)

    site = SimpleNamespace(
        id=9,
        archived=True,
        documents=[SimpleNamespace(stored_name="gone.pdf")],
        cost_estimates=[SimpleNamespace(attachments=[SimpleNamespace(stored_name="quote.pdf")])],
    )
    db = MagicMock()

    ids = purge_archived_sites(db, [site])

    assert ids == [9]
    db.delete.assert_called_once_with(site)
    db.commit.assert_called_once()
    assert not doc.exists()
    assert not att.exists()
    assert leftover.exists()


def test_purge_archived_sites_rolls_back_on_active(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.UPLOAD_DIR", tmp_path)
    monkeypatch.setattr("app.storage.ARCHIVE_DIR", tmp_path / "archive")
    active = SimpleNamespace(id=1, archived=False, documents=[], cost_estimates=[])
    db = MagicMock()
    with pytest.raises(HTTPException) as exc:
        purge_archived_sites(db, [active])
    assert exc.value.status_code == 409
    db.delete.assert_not_called()
    db.commit.assert_not_called()
