"""Archive-only hard delete / purge guards."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.routers.sites import (
    _site_file_paths,
    purge_archived_sites,
    require_archived_for_purge,
)
from app.storage_paths import cost_estimates_dir, documents_dir


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
    assert paths[0] == documents_dir() / "12_abc.pdf"
    assert paths[1] == cost_estimates_dir() / "quote.pdf"


def test_purge_archived_sites_deletes_and_unlinks(tmp_path, monkeypatch):
    upload = tmp_path / "uploads"
    estimates = upload / "cost-estimates"
    estimates.mkdir(parents=True)
    doc = upload / "gone.pdf"
    att = estimates / "quote.pdf"
    doc.write_text("doc")
    att.write_text("att")
    leftover = upload / "keep.pdf"
    leftover.write_text("keep")

    monkeypatch.setattr("app.routers.sites.documents_dir", lambda: upload)
    monkeypatch.setattr("app.routers.sites.cost_estimates_dir", lambda: estimates)

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
    monkeypatch.setattr("app.routers.sites.documents_dir", lambda: tmp_path)
    monkeypatch.setattr("app.routers.sites.cost_estimates_dir", lambda: tmp_path / "cost-estimates")
    active = SimpleNamespace(id=1, archived=False, documents=[], cost_estimates=[])
    db = MagicMock()
    with pytest.raises(HTTPException) as exc:
        purge_archived_sites(db, [active])
    assert exc.value.status_code == 409
    db.delete.assert_not_called()
    db.commit.assert_not_called()
