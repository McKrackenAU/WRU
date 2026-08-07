"""Actual spend rate-based calculation helpers."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.routers.spend import _calculate_spend, _hydrate_asphalt_lines


def test_hydrate_asphalt_lines_fills_rates_from_db():
    rate = SimpleNamespace(
        id=7,
        active=True,
        subcontractor_id=3,
        name="Mill",
        unit="m2",
        day_rate=10.0,
        night_rate=12.0,
        saturday_rate=14.0,
        sunday_rate=16.0,
        public_holiday_rate=18.0,
    )
    db = MagicMock()
    db.get.return_value = rate
    lines = _hydrate_asphalt_lines(db, [{"rate_id": 7, "quantity": 50}], 3)
    assert lines[0]["name"] == "Mill"
    assert lines[0]["day_rate"] == 10.0
    assert lines[0]["quantity"] == 50


def test_hydrate_rejects_wrong_subcontractor():
    rate = SimpleNamespace(id=7, active=True, subcontractor_id=99)
    db = MagicMock()
    db.get.return_value = rate
    with pytest.raises(HTTPException) as exc:
        _hydrate_asphalt_lines(db, [{"rate_id": 7, "quantity": 1}], 3)
    assert exc.value.status_code == 400


def test_calculate_asphalt_spend_from_hydrated_rates():
    rate = SimpleNamespace(
        id=1,
        active=True,
        subcontractor_id=2,
        name="Pave",
        unit="t",
        day_rate=100.0,
        night_rate=120.0,
        saturday_rate=130.0,
        sunday_rate=140.0,
        public_holiday_rate=150.0,
    )
    sub = SimpleNamespace(id=2, name="Bitumax")
    db = MagicMock()
    db.get.side_effect = lambda model, pk: rate if pk == 1 else sub

    amount, inputs, results = _calculate_spend(
        db,
        kind="asphalt",
        work_date=date(2026, 7, 28),  # Tuesday
        asphalt_subcontractor_id=2,
        inputs={"shift_type": "day", "lines": [{"rate_id": 1, "quantity": 2.5}]},
    )
    assert amount == 250.0
    assert results["total"] == 250.0
    assert results["subcontractor_name"] == "Bitumax"
    assert inputs["lines"][0]["day_rate"] == 100.0


def test_calculate_asphalt_requires_lines():
    db = MagicMock()
    with pytest.raises(HTTPException) as exc:
        _calculate_spend(
            db,
            kind="asphalt",
            work_date=date(2026, 7, 28),
            asphalt_subcontractor_id=None,
            inputs={"lines": []},
        )
    assert exc.value.status_code == 400
