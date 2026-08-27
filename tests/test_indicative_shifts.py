"""Indicative shifts on sites feed Gantt length and traffic cost work days."""

from types import SimpleNamespace
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas import SiteCreate, SiteUpdate
from app.services import indicative_shifts_count

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
GANTT_PY = (ROOT / "app/routers/gantt.py").read_text(encoding="utf-8")
GANTT_JS = (ROOT / "app/static/js/gantt.js").read_text(encoding="utf-8")
COSTS_JS = (ROOT / "app/static/js/costs.js").read_text(encoding="utf-8")
MODELS = (ROOT / "app/models.py").read_text(encoding="utf-8")
MIGRATE = (ROOT / "app/migrate.py").read_text(encoding="utf-8")


def test_indicative_shifts_count_defaults_and_clamps():
    assert indicative_shifts_count(None) == 1
    assert indicative_shifts_count(SimpleNamespace(indicative_shifts_count=None)) == 1
    assert indicative_shifts_count(SimpleNamespace(indicative_shifts_count=3)) == 3
    assert indicative_shifts_count(SimpleNamespace(indicative_shifts_count="3")) == 3
    assert indicative_shifts_count(SimpleNamespace(indicative_shifts_count=0)) == 1
    assert indicative_shifts_count(SimpleNamespace(indicative_shifts_count=900)) == 365
    assert indicative_shifts_count(SimpleNamespace(indicative_shifts_count="nope")) == 1


def test_site_schema_accepts_indicative_shifts():
    created = SiteCreate(road_name="DYNON RD - 5035", site_number="S48", indicative_shifts_count=3)
    assert created.indicative_shifts_count == 3
    updated = SiteUpdate(indicative_shifts_count=5)
    assert updated.indicative_shifts_count == 5
    with pytest.raises(ValidationError):
        SiteUpdate(indicative_shifts_count=0)


def test_drawer_and_register_expose_shifts():
    assert 'id="fShifts"' in INDEX
    assert "Indicative shifts" in INDEX
    assert "indicative_shifts_count" in APP_JS
    assert 'sortHeader("shifts", "Shifts")' in APP_JS
    assert "site.indicative_shifts_count" in APP_JS
    assert "indicative_shifts_count" in MODELS
    assert 'ensure_column("sites", "indicative_shifts_count"' in MIGRATE


def test_gantt_seeds_shifts_from_site():
    assert "shifts_count=indicative_shifts_count(site)" in GANTT_PY
    assert "syncAddShiftsFromSite" in GANTT_JS
    assert "siteIndicativeShifts" in GANTT_JS


def test_traffic_costs_prefill_from_site_shifts():
    assert "function applySiteScheduleDefaults" in COSTS_JS
    assert "applySiteScheduleDefaults(selectedSite()" in COSTS_JS
    assert "$(\"sDays\").value" in COSTS_JS or '$("sDays").value' in COSTS_JS
