"""Unit tests for asphalt costing and gantt date cascading."""

from datetime import date

from app.asphalt_engine import calculate_asphalt, pick_tier_rate
from app.gantt_engine import compute_item_window, next_work_day_after


def test_pick_tier_rate_fallbacks():
    rate = {"day_rate": 10, "night_rate": 0, "saturday_rate": 0, "sunday_rate": 0, "public_holiday_rate": 0}
    assert pick_tier_rate(rate, "weekday") == 10
    assert pick_tier_rate(rate, "night") == 10
    assert pick_tier_rate(rate, "saturday") == 10


def test_calculate_asphalt_total():
    out = calculate_asphalt(
        {
            "shift_type": "day",
            "contingency_pct": 10,
            "lines": [
                {"name": "Mill", "unit": "m2", "quantity": 100, "day_rate": 12},
                {"name": "Pave", "unit": "m2", "quantity": 100, "day_rate": 18},
            ],
        }
    )
    assert out["subtotal"] == 3000
    assert out["contingency"] == 300
    assert out["total"] == 3300
    assert len(out["lines"]) == 2


def test_gantt_skips_weekend_and_chains():
    # Friday 2026-07-31 + 1 shift → Fri; next after that should be Mon 2026-08-03
    start, end, schedule = compute_item_window(
        date(2026, 7, 31),
        1,
        work_weekdays=[0, 1, 2, 3, 4],
        skip_public_holidays=True,
        skip_sunday_before_monday_ph=True,
        rdo_dates=set(),
        include_dates=set(),
        exclude_dates=set(),
    )
    assert start == date(2026, 7, 31)
    assert end == date(2026, 7, 31)
    assert len(schedule) == 1

    nxt = next_work_day_after(
        end,
        work_weekdays=[0, 1, 2, 3, 4],
        skip_public_holidays=True,
        skip_sunday_before_monday_ph=True,
        rdo_dates=set(),
        include_dates=set(),
        exclude_dates=set(),
    )
    assert nxt == date(2026, 8, 3)


def test_gantt_respects_rdo():
    # Mon start, RDO on Tuesday → 2 shifts land Mon + Wed
    start, end, schedule = compute_item_window(
        date(2026, 8, 3),
        2,
        work_weekdays=[0, 1, 2, 3, 4],
        skip_public_holidays=True,
        skip_sunday_before_monday_ph=True,
        rdo_dates={date(2026, 8, 4)},
        include_dates=set(),
        exclude_dates=set(),
    )
    assert [d["date"] for d in schedule] == ["2026-08-03", "2026-08-05"]
    assert start == date(2026, 8, 3)
    assert end == date(2026, 8, 5)
