#!/usr/bin/env python3
"""Seed sample WRU TGS Tracker data."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import CustomColumn, Site, TrackingEvent  # noqa: E402
from app.services import apply_workflow, ensure_workflow_steps  # noqa: E402


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(Site).count():
            print("Database already has sites; skipping seed.")
            return

        today = date.today()
        samples = [
            {
                "road_name": "DYNON RD - 5035",
                "site_number": "S48",
                "indicative_site_start_date": today + timedelta(days=45),
                "moa_must_have_received_date": today + timedelta(days=30),
                "comments": "Ventia to review - 3x comments made Re: detours",
                "moa_number": "0093225",
                "moa_submission_date": today - timedelta(days=12),
                "workflow": {
                    "tgs_markup_completed": True,
                    "submitted_to_tmd": True,
                    "plan_received": True,
                    "ready_to_submit_moa": True,
                    "moa_submitted": True,
                    "moa_with_trims": True,
                },
                "tracking": "TRIMS Submitted 23/7",
            },
            {
                "road_name": "HOPKINS-WHITEHALL ST - 5880",
                "site_number": "S49",
                "indicative_site_start_date": today + timedelta(days=18),
                "moa_must_have_received_date": today + timedelta(days=5),
                "comments": "Awaiting revised TGS from designer",
                "moa_number": None,
                "moa_submission_date": None,
                "workflow": {
                    "tgs_markup_completed": True,
                    "submitted_to_tmd": True,
                    "plan_received": True,
                    "ready_to_submit_moa": True,
                },
                "tracking": "Ready to submit MoA once comments cleared",
            },
            {
                "road_name": "FOOTSCRAY RD - 4120",
                "site_number": "S50",
                "indicative_site_start_date": today + timedelta(days=60),
                "moa_must_have_received_date": today + timedelta(days=40),
                "comments": "Plan received from consultant",
                "moa_number": None,
                "moa_submission_date": None,
                "workflow": {
                    "tgs_markup_completed": True,
                    "submitted_to_tmd": True,
                    "plan_received": True,
                },
                "tracking": "Plan Received – checking detour extents",
            },
            {
                "road_name": "BALLARAT RD - 3312",
                "site_number": "S51",
                "indicative_site_start_date": today + timedelta(days=10),
                "moa_must_have_received_date": today - timedelta(days=2),
                "comments": "Priority – MoA overdue vs must-have date",
                "moa_number": "0093401",
                "moa_submission_date": today - timedelta(days=5),
                "workflow": {
                    "tgs_markup_completed": True,
                    "submitted_to_tmd": True,
                    "plan_received": True,
                    "ready_to_submit_moa": True,
                    "moa_submitted": True,
                },
                "tracking": "Chasing TRIMS for turnaround",
            },
        ]

        for row in samples:
            tracking_msg = row.pop("tracking")
            workflow = row.pop("workflow")
            site = Site(**row, custom_fields={})
            db.add(site)
            db.flush()
            ensure_workflow_steps(site)
            apply_workflow(site, workflow)
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
        db.add(
            CustomColumn(
                name="Council Area",
                field_key="council_area",
                field_type="select",
                options=["Maribyrnong", "Melbourne", "Hobsons Bay"],
                position=2,
                created_by="seed",
            )
        )

        # Attach sample custom field values
        sites = db.query(Site).all()
        if sites:
            sites[0].custom_fields = {
                "permit_officer": "A. Nguyen",
                "council_area": "Maribyrnong",
            }
            sites[1].custom_fields = {
                "permit_officer": "J. Patel",
                "council_area": "Melbourne",
            }

        db.commit()
        print(f"Seeded {len(samples)} sites and 2 custom columns.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
