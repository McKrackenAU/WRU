"""Unit tests for resource pack allocation and costing."""

from __future__ import annotations

from types import SimpleNamespace

from app.cost_engine import allocate_resource_packs, calculate_standard


def _pack(id_, people, vehicle, day_o, *, kind="crew_pack", name=None, pos=0):
    return SimpleNamespace(
        id=id_,
        name=name or f"{people}p{'+v' if vehicle else ''}",
        rate_kind=kind,
        pack_people=people,
        includes_vehicle=vehicle,
        day_ordinary=day_o,
        day_overtime=day_o * 1.5,
        night_ordinary=day_o * 1.2,
        night_overtime=day_o * 1.7,
        active=True,
        position=pos,
    )


def test_allocates_example_10_people_8_vehicles_2_tmas():
    rates = [
        _pack(1, 1, False, 55, pos=1),
        _pack(2, 2, False, 100, pos=2),
        _pack(3, 3, False, 145, pos=3),
        _pack(4, 4, False, 180, pos=4),
        _pack(5, 1, True, 80, pos=5),
        _pack(6, 2, True, 130, pos=6),
        _pack(7, 3, True, 175, pos=7),
        _pack(8, 4, True, 210, pos=8),
        _pack(9, 0, True, 180, kind="tma", name="TMA", pos=9),
    ]
    result = allocate_resource_packs(
        people=10,
        vehicles=8,
        tmas=2,
        rates=rates,
        shift_hours=8,
        shift_type="day",
        overtime_after=8,
    )
    alloc = result["allocation"]
    assert alloc["requested"] == {"people": 10, "vehicles": 8, "tmas": 2}
    assert alloc["covered"]["people"] >= 10
    assert alloc["covered"]["vehicles"] >= 8
    assert alloc["covered"]["tmas"] == 2
    # TMAs must appear and not inflate people coverage requirement
    tma_lines = [l for l in result["lines"] if l["rate_kind"] == "tma"]
    assert len(tma_lines) == 1
    assert tma_lines[0]["quantity"] == 2
    assert result["shift_labour_total"] > 0


def test_prefers_cheaper_larger_pack():
    rates = [
        _pack(1, 1, False, 60),
        _pack(2, 4, False, 100),  # much cheaper per head
    ]
    result = allocate_resource_packs(
        people=4,
        vehicles=0,
        tmas=0,
        rates=rates,
        shift_hours=8,
        shift_type="day",
        overtime_after=8,
    )
    by_id = {l["rate_id"]: l["quantity"] for l in result["lines"]}
    assert by_id.get(2) == 1
    assert by_id.get(1, 0) == 0
    assert result["shift_labour_total"] == 100 * 8


def test_standard_uses_resources_payload():
    rates = [
        _pack(1, 1, False, 50),
        _pack(2, 1, True, 70),
        _pack(3, 0, True, 200, kind="tma", name="TMA"),
    ]
    settings = SimpleNamespace(
        overtime_after_hours=8,
        vms_lead_days_default=0,
        vms_delivery_rate=0,
        vms_collection_rate=0,
        vms_day_rate=0,
    )
    out = calculate_standard(
        {
            "total_shifts": 1,
            "shift_hours": 8,
            "shift_type": "day",
            "works_start": "2026-08-01",
            "works_end": "2026-08-01",
            "vms_quantity": 0,
            "resources": {"people": 2, "vehicles": 1, "tmas": 1},
        },
        settings,
        rates,
    )
    assert out["per_shift"]["allocation"]["requested"]["people"] == 2
    assert out["site_traffic_total"] == out["site_labour_total"]
