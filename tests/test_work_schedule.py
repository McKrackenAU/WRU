"""Work-day schedule, Victorian PH, and weekend rate tiers."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.cost_engine import (
    build_work_schedule,
    calculate_standard,
    classify_rate_tier,
    rate_unit_rates,
)
from app.public_holidays import easter_sunday, is_public_holiday, victorian_holidays


def test_easter_and_vic_cup_day():
    assert easter_sunday(2026) == date(2026, 4, 5)
    hols = victorian_holidays(2026)
    assert date(2026, 11, 3) in hols  # Melbourne Cup 2026
    assert is_public_holiday(date(2026, 1, 26)) or is_public_holiday(date(2026, 1, 27))


def test_sun_thu_skips_saturday_and_ph():
    # Start Fri 2026-08-07; need 5 Sun–Thu days, skip PH
    rows = build_work_schedule(
        date(2026, 8, 7),
        5,
        work_weekdays=[6, 0, 1, 2, 3],  # Sun–Thu
        skip_public_holidays=True,
        skip_sunday_before_monday_ph=False,
    )
    dates = [r["date"] for r in rows]
    assert "2026-08-08" not in dates  # Saturday
    assert dates[0] == "2026-08-09"  # Sunday
    assert all(date.fromisoformat(d).weekday() in {6, 0, 1, 2, 3} for d in dates)


def test_skip_sunday_when_monday_ph():
    # Australia Day 2026 is Monday 26 Jan (observed from Sun 25? Jan 26 is Monday)
    # King's Birthday 2026 is Monday 8 June — preceding Sunday 7 June should skip
    rows = build_work_schedule(
        date(2026, 6, 5),
        3,
        work_weekdays=[4, 5, 6, 0, 1],  # Fri–Tue
        skip_public_holidays=True,
        skip_sunday_before_monday_ph=True,
    )
    dates = {r["date"] for r in rows}
    assert "2026-06-07" not in dates  # Sunday before King's Birthday
    assert "2026-06-08" not in dates  # PH Monday


def test_rdo_and_force_work_ph():
    rows = build_work_schedule(
        date(2026, 6, 5),
        2,
        work_weekdays=[0, 1, 2, 3, 4],
        skip_public_holidays=True,
        rdo_dates={date(2026, 6, 9)},
        include_dates={date(2026, 6, 8)},  # work King's Birthday
    )
    dates = [r["date"] for r in rows]
    assert "2026-06-08" in dates
    assert "2026-06-09" not in dates
    assert classify_rate_tier(date(2026, 6, 8)) == "public_holiday"


def _pack(**kwargs):
    base = dict(
        id=1,
        name="2 TC + vehicle",
        rate_kind="crew_pack",
        pack_people=2,
        includes_vehicle=True,
        day_ordinary=100,
        day_overtime=140,
        night_ordinary=120,
        night_overtime=170,
        saturday_ordinary=150,
        saturday_overtime=190,
        sunday_ordinary=200,
        sunday_overtime=240,
        public_holiday_ordinary=220,
        public_holiday_overtime=260,
        active=True,
        position=1,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_rate_tiers_use_weekend_columns():
    rate = _pack()
    assert rate_unit_rates(rate, "day", "weekday") == (100, 140)
    assert rate_unit_rates(rate, "day", "saturday") == (150, 190)
    assert rate_unit_rates(rate, "night", "sunday") == (200, 240)
    assert rate_unit_rates(rate, "day", "public_holiday") == (220, 260)


def test_standard_uses_work_dates_and_tiers():
    rates = [
        _pack(),
        SimpleNamespace(
            id=9,
            name="TMA",
            rate_kind="tma",
            pack_people=0,
            includes_vehicle=True,
            day_ordinary=180,
            day_overtime=220,
            night_ordinary=200,
            night_overtime=250,
            saturday_ordinary=0,
            saturday_overtime=0,
            sunday_ordinary=0,
            sunday_overtime=0,
            public_holiday_ordinary=0,
            public_holiday_overtime=0,
            active=True,
            position=9,
        ),
    ]
    settings = SimpleNamespace(
        overtime_after_hours=8,
        vms_lead_days_default=0,
        vms_delivery_rate=0,
        vms_collection_rate=0,
        vms_day_rate=0,
        travel_allowance=0,
        meal_allowance=0,
        meal_after_hours=9.5,
        day_start_hour=6.0,
        day_end_hour=18.0,
    )
    out = calculate_standard(
        {
            "works_start": "2026-08-08",
            "days_of_work": 2,
            "shifts_per_day": 1,
            "shift_hours": 8,
            "shift_type": "day",
            "work_weekdays": [5, 6],  # Sat + Sun
            "skip_public_holidays": True,
            "vms_quantity": 0,
            "resources": {"people": 2, "vehicles": 1, "tmas": 0, "spotters": 0},
        },
        settings,
        rates,
    )
    assert out["inputs_echo"]["total_shifts"] == 2
    assert out["schedule"][0]["rate_tier"] == "saturday"
    assert out["schedule"][1]["rate_tier"] == "sunday"
    # Sat 8h × 150 + Sun 8h × 200 = 1200 + 1600 = 2800
    assert out["site_crew_total"] == 2800.0
