#!/usr/bin/env python3
"""Seed sample WRU TGS Tracker data."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import SessionLocal  # noqa: E402
from app.financial_year import australian_financial_year  # noqa: E402
from app.migrate import run_migrations  # noqa: E402
from app.models import CustomColumn, Site, TrackingEvent  # noqa: E402
from app.services import apply_workflow, ensure_workflow_steps, set_councils  # noqa: E402


def main() -> None:
    run_migrations()
    db = SessionLocal()
    try:
        if db.query(Site).count():
            print("Database already has sites; skipping seed.")
            return

        today = date.today()
        fy = australian_financial_year(today)
        samples = [
            {
                "road_name": "DYNON RD - 5035",
                "site_number": "S48",
                "program": "Lifecycle pavements",
                "tgs_reference": "TGS-5035-A",
                "indicative_site_start_date": today + timedelta(days=45),
                "indicative_shifts_count": 3,
                "moa_must_have_received_date": today + timedelta(days=30),
                "comments": "Ventia to review - 3x comments made Re: detours",
                "moa_number": "0093225",
                "moa_submission_date": today - timedelta(days=12),
                "councils": [
                    {
                        "council_name": "Maribyrnong",
                        "submitted_to_council_date": today - timedelta(days=18),
                        "no_objection_date": None,
                    }
                ],
                "workflow": {
                    "tgs_markup_completed": True,
                    "submitted_to_tmd": True,
                    "ventia_review": True,
                    "plan_received": True,
                    "ready_to_submit_moa": True,
                    "moa_submitted": True,
                    "moa_with_trims": True,
                },
                "tracking": "TRIMS Submitted 23/7",
                "custom_fields": {"permit_officer": "A. Nguyen"},
            },
            {
                "road_name": "HOPKINS-WHITEHALL ST - 5880",
                "site_number": "S49",
                "program": "Lifecycle structures",
                "tgs_reference": "TGS-5880-B",
                "indicative_site_start_date": today + timedelta(days=18),
                "moa_must_have_received_date": today + timedelta(days=5),
                "comments": "Awaiting revised TGS from designer",
                "moa_number": None,
                "moa_submission_date": None,
                "councils": ["Melbourne", "Maribyrnong"],
                "workflow": {
                    "tgs_markup_completed": True,
                    "submitted_to_tmd": True,
                    "ventia_review": True,
                    "plan_received": True,
                    "ready_to_submit_moa": True,
                },
                "tracking": "Ready to submit MoA once comments cleared",
                "custom_fields": {"permit_officer": "J. Patel"},
            },
            {
                "road_name": "FOOTSCRAY RD - 4120",
                "site_number": "S50",
                "program": "Assets",
                "tgs_reference": "TGS-4120-A",
                "indicative_site_start_date": today + timedelta(days=60),
                "moa_must_have_received_date": today + timedelta(days=40),
                "comments": "Plan received from consultant",
                "moa_number": None,
                "moa_submission_date": None,
                "councils": ["Maribyrnong"],
                "workflow": {
                    "tgs_markup_completed": True,
                    "submitted_to_tmd": True,
                    "ventia_review": True,
                    "plan_received": True,
                },
                "tracking": "Plan Received - checking detour extents",
                "custom_fields": {},
            },
            {
                "road_name": "BALLARAT RD - 3312",
                "site_number": "S51",
                "program": "Routine maintenance",
                "tgs_reference": "TGS-3312-C",
                "indicative_site_start_date": today + timedelta(days=10),
                "moa_must_have_received_date": today - timedelta(days=2),
                "comments": "Priority - MoA overdue vs must-have date",
                "moa_number": "0093401",
                "moa_submission_date": today - timedelta(days=5),
                "councils": [
                    {
                        "council_name": "Hobsons Bay",
                        "submitted_to_council_date": today - timedelta(days=40),
                        "no_objection_date": None,
                    },
                    {
                        "council_name": "Maribyrnong",
                        "submitted_to_council_date": today - timedelta(days=8),
                        "no_objection_date": today - timedelta(days=1),
                    },
                ],
                "workflow": {
                    "tgs_markup_completed": True,
                    "submitted_to_tmd": True,
                    "ventia_review": True,
                    "plan_received": True,
                    "ready_to_submit_moa": True,
                    "moa_submitted": True,
                },
                "tracking": "Chasing TRIMS for turnaround",
                "custom_fields": {},
            },
        ]

        for row in samples:
            tracking_msg = row.pop("tracking")
            workflow = row.pop("workflow")
            councils = row.pop("councils")
            custom_fields = row.pop("custom_fields")
            site = Site(**row, custom_fields=custom_fields, financial_year=fy, archived=False)
            db.add(site)
            db.flush()
            ensure_workflow_steps(site, db)
            apply_workflow(site, workflow, db)
            set_councils(site, councils)
            db.add(
                TrackingEvent(
                    site_id=site.id,
                    event_type="status",
                    message=tracking_msg,
                    created_by="seed",
                )
            )

        db.add(
            CustomColumn(
                name="Permit Officer",
                field_key="permit_officer",
                field_type="text",
                position=1,
                created_by="seed",
            )
        )

        db.commit()
        print(f"Seeded {len(samples)} sites for FY {fy}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
