"""Permits / TRIMS mutual exclusion, council business-day wait, progress."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from app.business_days import add_business_days, business_days_elapsed
from app.calculations import (
    COUNCIL_NO_OBJECTION_BUSINESS_DAYS,
    client_list_bucket,
    council_wait_metrics,
    current_stage_key,
    site_metrics,
    workflow_progress_pct,
)
from app.models import WORKFLOW_STAGES
from app.stage_registry import DEFAULT_STAGES


def _roles() -> dict[str, str]:
    return {s["key"]: s["list_role"] for s in DEFAULT_STAGES}


def _progress_keys() -> set[str]:
    return {s["key"] for s in DEFAULT_STAGES if s["counts_toward_progress"]}


def _site(completed: list[str], *, councils=None):
    steps = [
        SimpleNamespace(stage=k, completed=(k in completed))
        for k in WORKFLOW_STAGES
    ]
    return SimpleNamespace(
        workflow_steps=steps,
        councils=councils or [],
        indicative_site_start_date=None,
        moa_must_have_received_date=None,
        must_have_manual=False,
        moa_submission_date=None,
        moa_received_date=None,
        moa_expiry_date=None,
        extension_submission_date=None,
        extension_received_date=None,
        extension_expiry_date=None,
    )


def test_not_submitted_to_dtp_off_both_lists():
    site = _site(["tgs_markup_completed", "submitted_to_tmd", "ventia_review", "plan_received"])
    assert client_list_bucket(site, stage_keys=WORKFLOW_STAGES, list_roles=_roles()) == "none"
    m = site_metrics(site, stage_keys=WORKFLOW_STAGES, list_roles=_roles())
    assert m["on_permits_priority_list"] is False
    assert m["on_trims_priority_list"] is False


def test_waiting_to_submit_still_off_lists():
    site = _site(["ready_to_submit_moa"])
    assert client_list_bucket(site, stage_keys=WORKFLOW_STAGES, list_roles=_roles()) == "none"


def test_moa_submitted_on_permits_only():
    site = _site(["moa_submitted"])
    assert client_list_bucket(site, stage_keys=WORKFLOW_STAGES, list_roles=_roles()) == "permits"
    m = site_metrics(site, stage_keys=WORKFLOW_STAGES, list_roles=_roles())
    assert m["on_permits_priority_list"] is True
    assert m["on_trims_priority_list"] is False


def test_trims_moves_off_permits():
    site = _site(["moa_submitted", "moa_with_trims"])
    assert client_list_bucket(site, stage_keys=WORKFLOW_STAGES, list_roles=_roles()) == "trims"
    m = site_metrics(site, stage_keys=WORKFLOW_STAGES, list_roles=_roles())
    assert m["on_permits_priority_list"] is False
    assert m["on_trims_priority_list"] is True


def test_revision_pulls_back_to_permits():
    site = _site(["moa_submitted", "moa_with_trims", "revision_needed"])
    assert client_list_bucket(site, stage_keys=WORKFLOW_STAGES, list_roles=_roles()) == "permits"


def test_received_removes_from_both_lists():
    site = _site(["moa_submitted", "moa_with_trims", "moa_received"])
    assert client_list_bucket(site, stage_keys=WORKFLOW_STAGES, list_roles=_roles()) == "none"
    site2 = _site(["moa_submitted", "ready_for_works"])
    assert client_list_bucket(site2, stage_keys=WORKFLOW_STAGES, list_roles=_roles()) == "none"


def test_progress_bar_pct_ignores_revision():
    site = _site(["tgs_markup_completed", "revision_needed"])
    pct = workflow_progress_pct(
        site, stage_keys=WORKFLOW_STAGES, progress_keys=_progress_keys()
    )
    # 1 of 9 progress stages
    assert pct == round(100 * 1 / 9)


def test_current_stage_none_when_nothing_complete():
    site = _site([])
    assert current_stage_key(site, WORKFLOW_STAGES) is None


def test_current_stage_is_furthest_configured_not_first_incomplete():
    site = _site(["tgs_markup_completed", "submitted_to_tmd", "moa_submitted"])
    assert current_stage_key(site, WORKFLOW_STAGES) == "moa_submitted"


def test_current_stage_ignores_orphan_step_keys():
    site = _site(["tgs_markup_completed", "submitted_to_tmd"])
    site.workflow_steps.append(SimpleNamespace(stage="legacy_orphan", completed=True))
    assert current_stage_key(site, WORKFLOW_STAGES) == "submitted_to_tmd"


def test_assign_stage_positions_keeps_payload_order():
    from app.routers.stages import assign_stage_positions

    assert assign_stage_positions([3, 1, 2], [1, 2, 3]) == {3: 10, 1: 20, 2: 30}
    assert assign_stage_positions([2], [1, 2, 3]) == {2: 10, 1: 20, 3: 30}


def test_progress_follows_configured_order_not_flag_count():
    site = _site(["moa_submitted"])
    progress = [k for k in WORKFLOW_STAGES if k != "revision_needed"]
    idx = progress.index("moa_submitted")
    pct = workflow_progress_pct(
        site, stage_keys=WORKFLOW_STAGES, progress_keys=set(progress)
    )
    assert pct == round(100 * (idx + 1) / len(progress))
    reordered = ["moa_submitted", "tgs_markup_completed", "ready_for_works"]
    pct2 = workflow_progress_pct(
        site, stage_keys=reordered, progress_keys=set(reordered)
    )
    assert pct2 == round(100 * 1 / 3)


def test_business_days_skip_weekend():
    friday = date(2026, 7, 24)  # Friday
    assert add_business_days(friday, 1) == date(2026, 7, 27)  # Monday
    assert add_business_days(friday, 10) == date(2026, 8, 7)
    assert business_days_elapsed(friday, date(2026, 7, 27)) == 1


def test_council_assumed_no_objection_after_configured_business_days():
    # Spreadsheet V6 default = 10 business days (was 21 in earlier app builds)
    submitted = date(2026, 6, 1)  # Monday
    assumed = add_business_days(submitted, COUNCIL_NO_OBJECTION_BUSINESS_DAYS)
    assert COUNCIL_NO_OBJECTION_BUSINESS_DAYS == 10
    council = SimpleNamespace(
        council_name="Test Council",
        submitted_to_council_date=submitted,
        no_objection_date=None,
    )
    site = _site([], councils=[council])
    waiting = council_wait_metrics(site, today=submitted + timedelta(days=5))
    assert waiting[0]["status"] == "waiting"
    assert waiting[0]["business_days_waiting"] == business_days_elapsed(
        submitted, submitted + timedelta(days=5)
    )

    done = council_wait_metrics(site, today=assumed)
    assert done[0]["status"] == "assumed_no_objection"
    assert done[0]["assumed_no_objection"] is True


def test_explicit_no_objection_preferred():
    council = SimpleNamespace(
        council_name="Test Council",
        submitted_to_council_date=date(2026, 6, 1),
        no_objection_date=date(2026, 6, 10),
    )
    site = _site([], councils=[council])
    rows = council_wait_metrics(site, today=date(2026, 8, 1))
    assert rows[0]["status"] == "no_objection"
    assert rows[0]["assumed_no_objection"] is False
