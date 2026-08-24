"""Asphalt rate typing, weekend fallback, and subcontractor comparison."""

from __future__ import annotations

from app.asphalt_engine import (
    calculate_asphalt,
    compare_subcontractors,
    infer_rate_type,
    pick_tier_rate,
    rate_card_matrix,
)


def test_msq_is_unit_rate():
    assert infer_rate_type("m2", "50mm HP Mill & Resheet") == "unit"
    assert infer_rate_type("Msq", "asphalt") == "unit"
    assert infer_rate_type("sqm") == "unit"


def test_mobilisation_and_crew_are_shift():
    assert infer_rate_type("lump", "Mobilisation") == "shift"
    assert infer_rate_type("shift", "Crew") == "shift"
    assert infer_rate_type("m2", "Crew establishment") == "shift"


def test_unit_item_ignores_tier():
    row = {"day_rate": 32.71, "night_rate": 32.71, "sunday_rate": 32.71, "saturday_rate": 32.71}
    assert pick_tier_rate(row, "weekday") == 32.71
    assert pick_tier_rate(row, "weekend") == 32.71
    assert pick_tier_rate(row, "night") == 32.71


def test_weekend_uses_sunday_rate():
    row = {"day_rate": 100, "night_rate": 120, "saturday_rate": 0, "sunday_rate": 150, "public_holiday_rate": 180}
    assert pick_tier_rate(row, "saturday") == 150
    assert pick_tier_rate(row, "sunday") == 150
    assert pick_tier_rate(row, "weekend") == 150
    assert pick_tier_rate(row, "public_holiday") == 180


def test_compare_picks_cheapest_complete_sub():
    lines = [{"name": "50mm HP Mill & Resheet", "unit": "m2", "quantity": 100}]
    subs = [
        {"id": 1, "name": "BORAL", "active": True},
        {"id": 2, "name": "RABS", "active": True},
        {"id": 3, "name": "PRESTIGE", "active": True},
    ]
    rates = [
        {"id": 10, "subcontractor_id": 1, "name": "50mm HP Mill & Resheet", "unit": "m2", "rate_type": "unit", "day_rate": 32.71, "active": True},
        {"id": 11, "subcontractor_id": 2, "name": "50mm HP Mill & Resheet", "unit": "m2", "rate_type": "unit", "day_rate": 33.89, "active": True},
        {"id": 12, "subcontractor_id": 3, "name": "50mm HP Mill & Resheet", "unit": "m2", "rate_type": "unit", "day_rate": 29.50, "active": True},
    ]
    out = compare_subcontractors(lines=lines, subcontractors=subs, rates=rates)
    assert out["best_subcontractor_name"] == "PRESTIGE"
    assert out["best_total"] == 2950.0
    mixed = out["mixed_best"]["lines"][0]["best"]
    assert mixed["subcontractor_name"] == "PRESTIGE"


def test_matrix_flags_best_cell():
    subs = [
        {"id": 1, "name": "BORAL", "active": True},
        {"id": 2, "name": "RABS", "active": True},
    ]
    rates = [
        {"id": 1, "subcontractor_id": 1, "name": "50mm HP Mill & Resheet", "unit": "m2", "rate_type": "unit", "day_rate": 32.71, "active": True},
        {"id": 2, "subcontractor_id": 2, "name": "50mm HP Mill & Resheet", "unit": "m2", "rate_type": "unit", "day_rate": 33.89, "active": True},
    ]
    matrix = rate_card_matrix(subcontractors=subs, rates=rates)
    row = matrix["treatments"][0]
    assert row["best_rate"] == 32.71
    boral = next(c for c in row["cells"] if c["subcontractor_name"] == "BORAL")
    rabs = next(c for c in row["cells"] if c["subcontractor_name"] == "RABS")
    assert boral["best"] is True
    assert rabs["best"] is False


def test_calculate_asphalt_unit_line():
    result = calculate_asphalt(
        {
            "shift_type": "day",
            "lines": [
                {
                    "name": "50mm HP Mill & Resheet",
                    "unit": "m2",
                    "rate_type": "unit",
                    "quantity": 10,
                    "day_rate": 29.5,
                }
            ],
        }
    )
    assert result["total"] == 295.0
