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


def test_gantt_night_shift_ends_next_morning():
    # 1 night shift on Sun 13 Sep 2026 (included) finishes Mon 14 Sep morning.
    start, end, schedule = compute_item_window(
        date(2026, 9, 13),
        1,
        work_weekdays=[0, 1, 2, 3, 4],
        skip_public_holidays=True,
        skip_sunday_before_monday_ph=True,
        rdo_dates=set(),
        include_dates={date(2026, 9, 13)},
        exclude_dates=set(),
        shift_type="night",
    )
    assert [d["date"] for d in schedule] == ["2026-09-13"]
    assert start == date(2026, 9, 13)
    assert end == date(2026, 9, 14)


def test_gantt_day_shift_stays_same_calendar_day():
    start, end, schedule = compute_item_window(
        date(2026, 9, 14),
        1,
        work_weekdays=[0, 1, 2, 3, 4],
        skip_public_holidays=True,
        skip_sunday_before_monday_ph=True,
        rdo_dates=set(),
        include_dates=set(),
        exclude_dates=set(),
        shift_type="day",
    )
    assert start == date(2026, 9, 14)
    assert end == date(2026, 9, 14)
    assert len(schedule) == 1


def test_gantt_night_cascade_uses_last_work_date():
    from types import SimpleNamespace

    from app.gantt_engine import recompute_board_dates

    board = SimpleNamespace(
        work_weekdays=[0, 1, 2, 3, 4],
        rdo_dates=[],
        exclude_dates=[],
        include_dates=[],
        skip_public_holidays=True,
        skip_sunday_before_monday_ph=True,
        anchor_start=date(2026, 9, 14),
    )

    def _item(*, item_id, position, shift_type, link_mode, fixed_start):
        return SimpleNamespace(
            id=item_id,
            board_id=1,
            site_id=item_id,
            position=position,
            shifts_count=1,
            shift_type=shift_type,
            link_mode=link_mode,
            fixed_start=fixed_start,
            subcontractor_id=None,
            traffic_contractor_id=None,
            planned_start=None,
            planned_end=None,
            rdo_dates=[],
            exclude_dates=[],
            include_dates=[],
            notes=None,
            site=None,
            subcontractor=None,
            traffic_contractor=None,
        )

    items = [
        _item(
            item_id=1,
            position=10,
            shift_type="night",
            link_mode="fixed_start",
            fixed_start=date(2026, 9, 14),
        ),
        _item(
            item_id=2,
            position=20,
            shift_type="day",
            link_mode="after_previous",
            fixed_start=None,
        ),
    ]
    recompute_board_dates(board, items)
    # Night display end is the following morning, but the next site can start that day.
    assert items[0].planned_start == date(2026, 9, 14)
    assert items[0].planned_end == date(2026, 9, 15)
    assert items[1].planned_start == date(2026, 9, 15)
    assert items[1].planned_end == date(2026, 9, 15)
