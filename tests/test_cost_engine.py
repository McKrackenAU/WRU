"""Unit tests for resource pack allocation, booking text, and allowances."""

from __future__ import annotations

from types import SimpleNamespace

from app.cost_engine import (
    allocate_resource_packs,
    calculate_closure_24h,
    calculate_standard,
    unit_shift_cost,
)


def _pack(id_, people, vehicle, day_o, *, kind="crew_pack", name=None, pos=0, day_ot=None):
    day_ot = day_o * 1.5 if day_ot is None else day_ot
    return SimpleNamespace(
        id=id_,
        name=name or f"{people}p{'+v' if vehicle else ''}",
        rate_kind=kind,
        pack_people=people,
        includes_vehicle=vehicle,
        day_ordinary=day_o,
        day_overtime=day_ot,
        night_ordinary=day_o * 1.2,
        night_overtime=day_o * 1.7,
        active=True,
        position=pos,
    )


def _default_rates():
    return [
        _pack(1, 1, False, 55, day_ot=75, pos=1, name="1 TC (no vehicle)"),
        _pack(2, 2, False, 100, day_ot=140, pos=2, name="2 TC (no vehicle)"),
        _pack(3, 3, False, 145, day_ot=200, pos=3, name="3 TC (no vehicle)"),
        _pack(4, 4, False, 180, day_ot=250, pos=4, name="4 TC (no vehicle)"),
        _pack(5, 1, True, 80, day_ot=100, pos=5, name="1 TC + vehicle"),
        _pack(6, 2, True, 130, day_ot=170, pos=6, name="2 TC + vehicle"),
        _pack(7, 3, True, 175, day_ot=230, pos=7, name="3 TC + vehicle"),
        _pack(8, 4, True, 210, day_ot=280, pos=8, name="4 TC + vehicle"),
        _pack(9, 0, True, 180, day_ot=220, kind="tma", name="TMA", pos=9),
        _pack(10, 1, False, 50, day_ot=70, kind="spotter", name="Spotter", pos=10),
    ]


def test_20_tc_10_vehicles_picks_cheapest_mix_not_naive_2tc_only():
    rates = _default_rates()
    result = allocate_resource_packs(
        people=20,
        vehicles=10,
        tmas=0,
        spotters=0,
        rates=rates,
        shift_hours=10,
        shift_type="day",
        overtime_after=8,
        travel_allowance=45,
        meal_allowance=30,
        meal_after_hours=9.5,
    )
    assert result["allocation"]["covered"]["people"] >= 20
    assert result["allocation"]["covered"]["vehicles"] >= 10
    assert result["booking_requirements"]
    assert "×" in result["booking_summary"]

    # Naive baseline: 10 × 2 TC + vehicle
    two_tc = next(r for r in rates if r.pack_people == 2 and r.includes_vehicle)
    naive = 10 * unit_shift_cost(
        two_tc, shift_type="day", ordinary_h=8, ot_h=2
    )
    assert result["shift_labour_total"] <= naive + 1e-6
    # With seeded placeholder rates the mixed larger packs beat pure 2TC crews
    assert result["shift_labour_total"] < naive - 1


def test_when_2tc_vehicle_dominates_books_ten_of_them():
    """If 2 TC + vehicle is clearly cheapest, booking should be 10× that pack."""
    rates = [
        _pack(1, 1, False, 200, pos=1),
        _pack(2, 2, False, 400, pos=2),
        _pack(3, 4, False, 800, pos=3),
        _pack(4, 1, True, 300, pos=4),
        _pack(5, 2, True, 100, pos=5, name="2 TC + vehicle"),  # very cheap
        _pack(6, 4, True, 500, pos=6),
    ]
    result = allocate_resource_packs(
        people=20,
        vehicles=10,
        tmas=0,
        rates=rates,
        shift_hours=8,
        shift_type="day",
        overtime_after=8,
    )
    by_label = {b["label"]: b["quantity"] for b in result["booking_requirements"]}
    assert by_label.get("2 TC + vehicle") == 10
    assert result["booking_summary"].startswith("10× 2 TC + vehicle")


def test_tma_and_spotter_get_allowances_not_in_tc_count():
    result = allocate_resource_packs(
        people=2,
        vehicles=1,
        tmas=2,
        spotters=1,
        rates=_default_rates(),
        shift_hours=8,
        shift_type="day",
        overtime_after=8,
        travel_allowance=45,
        meal_allowance=30,
        meal_after_hours=9.5,
    )
    kinds = {b["rate_kind"]: b["quantity"] for b in result["booking_requirements"]}
    assert kinds["tma"] == 2
    assert kinds["spotter"] == 1
    assert result["allowances"]["heads"] == 5  # 2 TC + 2 TMA drivers + 1 spotter
    assert result["allowances"]["meals_apply"] is False
    assert result["allowances"]["meal_total"] == 0
    assert result["allowances"]["travel_total"] == 5 * 45


def test_meals_apply_over_threshold():
    result = allocate_resource_packs(
        people=4,
        vehicles=0,
        tmas=0,
        spotters=0,
        rates=_default_rates(),
        shift_hours=10,
        shift_type="day",
        overtime_after=8,
        travel_allowance=45,
        meal_allowance=30,
        meal_after_hours=9.5,
    )
    assert result["allowances"]["meals_apply"] is True
    assert result["allowances"]["meal_total"] == 4 * 30
    assert result["shift_total"] == result["shift_labour_total"] + result["allowances"]["allowances_total"]


def _settings(**kwargs):
    base = dict(
        overtime_after_hours=8,
        vms_lead_days_default=0,
        vms_delivery_rate=0,
        vms_collection_rate=0,
        vms_day_rate=0,
        travel_allowance=45,
        meal_allowance=30,
        meal_after_hours=9.5,
        day_start_hour=6.0,
        day_end_hour=18.0,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_standard_includes_booking_and_allowances():
    out = calculate_standard(
        {
            "total_shifts": 1,
            "shift_hours": 10,
            "shift_type": "day",
            "works_start": "2026-08-01",
            "works_end": "2026-08-01",
            "vms_quantity": 0,
            "resources": {"people": 20, "vehicles": 10, "tmas": 0, "spotters": 0},
        },
        _settings(),
        _default_rates(),
    )
    assert out["booking_requirements"]
    assert out["per_shift"]["allowances"]["heads"] == 20
    assert out["per_shift"]["allowances"]["meal_total"] == 600
    assert out["site_traffic_total"] == out["site_crew_total"]


def test_days_of_work_from_shift_start_sets_end_and_shifts():
    out = calculate_standard(
        {
            "days_of_work": 5,
            "shifts_per_day": 1,
            "shift_hours": 10,
            "shift_start_time": "20:00",
            "works_start": "2026-08-01",
            "vms_quantity": 0,
            "resources": {"people": 4, "vehicles": 2, "tmas": 0, "spotters": 0},
        },
        _settings(),
        _default_rates(),
    )
    echo = out["inputs_echo"]
    assert echo["days_of_work"] == 5
    assert echo["works_start"] == "2026-08-01"
    assert echo["works_end"] == "2026-08-05"
    assert echo["total_shifts"] == 5
    assert echo["shift_type"] == "night"  # midpoint of 20:00+5h = 01:00


def test_night_window_config_classifies_day_shift():
    from app.cost_engine import classify_shift_type
    from datetime import datetime

    assert classify_shift_type(datetime(2026, 8, 1, 10, 0), day_start_hour=6, day_end_hour=18) == "day"
    assert classify_shift_type(datetime(2026, 8, 1, 22, 0), day_start_hour=6, day_end_hour=18) == "night"
    # Custom window: day = 07:00–19:00
    assert classify_shift_type(7.5, day_start_hour=7, day_end_hour=19) == "day"
    assert classify_shift_type(6.5, day_start_hour=7, day_end_hour=19) == "night"

def test_closure_8h_no_meals_12h_has_meals_and_marks_best():
    out = calculate_closure_24h(
        {
            "closure_start": "2026-08-07T18:00:00",
            "closure_end": "2026-08-10T06:00:00",
            "vms_quantity": 0,
            "resources": {"people": 4, "vehicles": 2, "tmas": 0, "spotters": 0},
        },
        _settings(),
        _default_rates(),
    )
    opt8 = out["option_3x8"]
    opt12 = out["option_2x12"]
    assert opt8["meals_apply_per_shift"] is False
    assert opt8["meal_total"] == 0
    assert opt8["travel_total"] > 0
    assert opt12["meals_apply_per_shift"] is True
    assert opt12["meal_total"] > 0
    assert opt12["travel_total"] > 0
    assert out["recommendation"]["best_label"]
    assert opt8["is_best"] or opt12["is_best"]
    assert opt8["grand_total"] == opt8["pack_labour_total"] + opt8["travel_total"] + opt8["meal_total"] + opt8["vms_total"]
    assert opt12["grand_total"] == opt12["pack_labour_total"] + opt12["travel_total"] + opt12["meal_total"] + opt12["vms_total"]


def test_exports_build_bytes():
    from app.cost_export import build_cost_pdf, build_cost_workbook

    out = calculate_closure_24h(
        {
            "closure_start": "2026-08-07T18:00:00",
            "closure_end": "2026-08-08T18:00:00",
            "vms_quantity": 0,
            "resources": {"people": 2, "vehicles": 1, "tmas": 0, "spotters": 0},
        },
        _settings(),
        _default_rates(),
    )
    xlsx = build_cost_workbook(out, title="Test closure")
    pdf = build_cost_pdf(out, title="Test closure")
    assert xlsx[:2] == b"PK"
    assert pdf.startswith(b"%PDF")
