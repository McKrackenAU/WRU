"""Tracker spreadsheet import — status aliases and unmatched rows."""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook

from app.tracker_import import _status_workflow, parse_tracker_workbook


def test_status_aliases_ready_for_works():
    wf, unmatched = _status_workflow("Ready For Works")
    assert unmatched is None
    assert wf["ready_for_works"] is True
    assert wf["moa_received"] is True


def test_status_submitted_to_traffic_management():
    wf, unmatched = _status_workflow("Submitted to traffic management")
    assert unmatched is None
    assert wf["submitted_to_tmd"] is True
    assert wf["ready_for_works"] is False


def test_blank_and_no_import_as_not_started():
    wf, unmatched = _status_workflow("")
    assert unmatched is None
    assert wf["tgs_markup_completed"] is False
    wf2, _ = _status_workflow("No")
    assert wf2["ready_for_works"] is False


def test_unknown_status_does_not_drop_row():
    wf, unmatched = _status_workflow("Waiting on designer")
    assert unmatched == "Waiting on designer"
    assert wf["ready_for_works"] is False


def _tracker_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "TGS-MOA Tracker"
    ws["A1"] = "LCP - FMRP"
    ws["B1"] = "Road Name"
    ws["B3"] = "HIGH ST - 1234"
    ws["C3"] = "S48"
    ws["G3"] = "Ready For Works"
    ws["R3"] = "0093225"
    ws["B4"] = "LOW ST - 99"
    ws["C4"] = "S1"
    ws["G4"] = "Waiting on designer"
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_keeps_unmatched_status_rows():
    parsed = parse_tracker_workbook(_tracker_bytes())
    assert parsed["parsed"] == 2
    roads = {r["road_name"] for r in parsed["rows"]}
    assert "HIGH ST - 1234" in roads
    assert "LOW ST - 99" in roads
    unmatched_row = next(r for r in parsed["rows"] if r["site_number"] == "S1")
    assert unmatched_row["status_unmatched"]
    assert "Waiting on designer" in parsed["unmatched_statuses"]
