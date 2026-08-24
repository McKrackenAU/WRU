"""Bulk rate-card CSV parsing."""

from __future__ import annotations

from app.rate_import import parse_tabular


def test_parse_csv_asphalt_headers():
    csv = (
        "subcontractor,name,unit,rate_type,unit_rate\n"
        "BORAL,50mm HP Mill & Resheet,m2,unit,32.71\n"
        "RABS,50mm HP Mill & Resheet,m2,unit,33.89\n"
    ).encode()
    rows = parse_tabular(csv, "rates.csv")
    assert rows[0][0] == "subcontractor"
    assert rows[1][0] == "BORAL"
    assert rows[2][4] == "33.89"
