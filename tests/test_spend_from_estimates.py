"""Seed actual spend from saved cost estimates."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.spend_from_estimates import (
    SOURCE_FROM_ESTIMATE,
    asphalt_estimate_total,
    sync_spend_from_estimates,
    traffic_estimate_total,
    upsert_spend_from_estimate,
)


def test_traffic_estimate_total_from_summary():
    est = SimpleNamespace(summary_total=1234.5, mode="standard", results={})
    assert traffic_estimate_total(est) == 1234.5


def test_traffic_estimate_total_from_results():
    est = SimpleNamespace(
        summary_total=None,
        mode="standard",
        results={"site_traffic_total": 999.0},
    )
    assert traffic_estimate_total(est) == 999.0


def test_asphalt_estimate_total():
    est = SimpleNamespace(summary_total=None, results={"total": 50.25})
    assert asphalt_estimate_total(est) == 50.25


def test_upsert_creates_from_estimate_row():
    db = MagicMock()
    # first() for seed lookup → None; first() for other spend → None
    chain = db.query.return_value.filter.return_value
    chain.order_by.return_value.first.return_value = None
    chain.first.return_value = None

    row, action = upsert_spend_from_estimate(
        db,
        kind="traffic",
        site_id=9,
        amount=100.0,
        estimate_id=3,
        estimate_name="Site package",
        created_by="tester",
    )
    assert action == "created"
    assert row.source == SOURCE_FROM_ESTIMATE
    assert row.amount == 100.0
    assert row.inputs["estimate_id"] == 3
    db.add.assert_called_once_with(row)


def test_upsert_skips_when_user_owned_spend_exists():
    db = MagicMock()
    chain = db.query.return_value.filter.return_value
    chain.order_by.return_value.first.return_value = None
    chain.first.return_value = SimpleNamespace(id=99, source="manual")

    row, action = upsert_spend_from_estimate(
        db,
        kind="traffic",
        site_id=9,
        amount=100.0,
        estimate_id=3,
        estimate_name="Site package",
    )
    assert action == "skipped_user_owned"
    assert row is None
    db.add.assert_not_called()


def test_upsert_updates_existing_seed_only():
    existing = SimpleNamespace(
        amount=10.0,
        inputs={},
        results={},
        category=None,
        notes=None,
        asphalt_subcontractor_id=None,
        traffic_contractor_id=None,
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = existing

    row, action = upsert_spend_from_estimate(
        db,
        kind="asphalt",
        site_id=9,
        amount=250.0,
        estimate_id=8,
        estimate_name="Mill/fill",
        asphalt_subcontractor_id=4,
    )
    assert action == "updated"
    assert row is existing
    assert existing.amount == 250.0
    assert existing.asphalt_subcontractor_id == 4
    db.add.assert_not_called()


def test_sync_uses_latest_estimate_per_site():
    older = SimpleNamespace(
        id=1,
        site_id=5,
        name="Old",
        summary_total=100.0,
        mode="standard",
        results={},
        created_by=None,
        created_at=None,
        subcontractor_id=None,
    )
    newer = SimpleNamespace(
        id=2,
        site_id=5,
        name="New",
        summary_total=200.0,
        mode="standard",
        results={},
        created_by=None,
        created_at=None,
        subcontractor_id=None,
    )
    db = MagicMock()

    traffic_q = MagicMock()
    asphalt_q = MagicMock()
    # First call CostEstimate query, second AsphaltEstimate
    db.query.side_effect = [traffic_q, asphalt_q]

    traffic_q.filter.return_value = traffic_q
    traffic_q.order_by.return_value.all.return_value = [newer, older]

    asphalt_q.filter.return_value = asphalt_q
    asphalt_q.order_by.return_value.all.return_value = []

    # upsert path: no existing seed
    seed_q = MagicMock()
    # After traffic/asphalt estimate queries, upsert calls db.query(ActualSpend)
    # Re-bind for subsequent ActualSpend lookups inside upsert
    def query_side_effect(model):
        name = getattr(model, "__name__", str(model))
        if name == "CostEstimate":
            return traffic_q
        if name == "AsphaltEstimate":
            return asphalt_q
        return seed_q

    db.query.side_effect = query_side_effect
    filtered = seed_q.filter.return_value
    filtered.order_by.return_value.first.return_value = None
    filtered.first.return_value = None

    counts = sync_spend_from_estimates(db)
    assert counts["created"] == 1
    assert counts["updated"] == 0
    db.commit.assert_called_once()
    created = db.add.call_args[0][0]
    assert created.amount == 200.0
    assert created.inputs["estimate_id"] == 2
