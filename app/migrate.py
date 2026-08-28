"""Lightweight schema upgrade for existing PostgreSQL databases."""

from __future__ import annotations

import sys

from sqlalchemy import inspect, text

from .database import Base, engine
from .models import (  # noqa: F401 — register metadata
    ActualSpend,
    AppSettings,
    AsphaltEstimate,
    AsphaltRate,
    AsphaltSubcontractor,
    CostEstimate,
    CostEstimateAttachment,
    CostSettings,
    CustomColumn,
    Document,
    DocumentCategoryDef,
    GanttBoard,
    GanttItem,
    LabourRate,
    LookupItem,
    MapFeature,
    MapLayer,
    ProgramCategory,
    ShiftExtraRate,
    Site,
    SiteCouncil,
    TrackingEvent,
    TrafficContractor,
    User,
    WorkflowStageDef,
    WorkflowStep,
)


def _warn(what: str, exc: BaseException) -> None:
    print(f"WRU migration warning ({what}): {exc}", file=sys.stderr)


def column_names(table: str) -> set[str]:
    try:
        insp = inspect(engine)
        if table not in insp.get_table_names():
            return set()
        return {c["name"] for c in insp.get_columns(table)}
    except Exception as exc:  # noqa: BLE001 — boot even if inspect fails
        _warn(f"inspect {table}", exc)
        return set()


def ensure_column(table: str, column: str, ddl: str) -> None:
    try:
        names = column_names(table)
        if not names:
            return
        if column in names:
            return
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
    except Exception as exc:  # noqa: BLE001
        _warn(f"ensure_column {table}.{column}", exc)


def run_migrations() -> None:
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as exc:  # noqa: BLE001
        _warn("create_all", exc)
        return

    # sites expansions
    ensure_column("sites", "program", "program VARCHAR(128)")
    ensure_column("sites", "tgs_reference", "tgs_reference VARCHAR(128)")
    ensure_column("sites", "financial_year", "financial_year VARCHAR(16)")
    ensure_column("sites", "archived", "archived BOOLEAN NOT NULL DEFAULT FALSE")
    ensure_column("sites", "archived_at", "archived_at TIMESTAMPTZ")
    ensure_column("sites", "archived_fy", "archived_fy VARCHAR(16)")
    ensure_column("sites", "must_have_manual", "must_have_manual BOOLEAN NOT NULL DEFAULT FALSE")
    ensure_column("sites", "priority_manual", "priority_manual INTEGER")
    ensure_column("sites", "moa_received_date", "moa_received_date DATE")
    ensure_column("sites", "moa_start_date", "moa_start_date DATE")
    ensure_column("sites", "moa_expiry_date", "moa_expiry_date DATE")
    ensure_column("sites", "extension_flag", "extension_flag VARCHAR(16)")
    ensure_column("sites", "extension_submission_date", "extension_submission_date DATE")
    ensure_column("sites", "extension_received_date", "extension_received_date DATE")
    ensure_column("sites", "extension_start_date", "extension_start_date DATE")
    ensure_column("sites", "extension_expiry_date", "extension_expiry_date DATE")
    ensure_column("sites", "job_completed_date", "job_completed_date DATE")
    ensure_column("sites", "include_in_totals", "include_in_totals BOOLEAN NOT NULL DEFAULT TRUE")
    ensure_column("sites", "register_order", "register_order INTEGER")
    ensure_column("sites", "indicative_shifts_count", "indicative_shifts_count INTEGER")
    ensure_column(
        "sites",
        "indicative_shift_type",
        "indicative_shift_type VARCHAR(16) NOT NULL DEFAULT 'day'",
    )
    ensure_column(
        "gantt_items",
        "traffic_contractor_id",
        "traffic_contractor_id INTEGER REFERENCES traffic_contractors(id) ON DELETE SET NULL",
    )
    ensure_column(
        "gantt_items",
        "shift_type",
        "shift_type VARCHAR(16) NOT NULL DEFAULT 'day'",
    )
    ensure_column(
        "gantt_boards",
        "schedule_saved",
        "schedule_saved BOOLEAN NOT NULL DEFAULT FALSE",
    )
    ensure_column("gantt_boards", "saved_at", "saved_at TIMESTAMPTZ")
    ensure_column("actual_spends", "source", "source VARCHAR(16) NOT NULL DEFAULT 'manual'")
    ensure_column("actual_spends", "inputs", "inputs JSONB NOT NULL DEFAULT '{}'::jsonb")
    ensure_column("actual_spends", "results", "results JSONB NOT NULL DEFAULT '{}'::jsonb")
    ensure_column("asphalt_rates", "rate_type", "rate_type VARCHAR(16) NOT NULL DEFAULT 'unit'")
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE asphalt_rates
                    SET rate_type = 'shift'
                    WHERE rate_type = 'unit'
                      AND (
                        lower(unit) IN ('shift', 'day', 'crew', 'mob', 'mobilisation', 'mobilization')
                        OR lower(name) LIKE '%mobilis%'
                        OR lower(name) LIKE '%mobiliz%'
                        OR lower(name) LIKE '%crew%'
                      )
                    """
                )
            )
    except Exception as exc:  # noqa: BLE001
        _warn("asphalt_rates rate_type", exc)

    # Seed register_order from current start-date ordering when missing
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    WITH ranked AS (
                      SELECT id,
                             ROW_NUMBER() OVER (
                               PARTITION BY COALESCE(NULLIF(BTRIM(program), ''), 'Unassigned')
                               ORDER BY indicative_site_start_date ASC NULLS LAST, id ASC
                             ) * 10 AS ord
                      FROM sites
                      WHERE register_order IS NULL
                    )
                    UPDATE sites
                    SET register_order = ranked.ord
                    FROM ranked
                    WHERE sites.id = ranked.id
                    """
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_sites_register_order ON sites (register_order)"))
    except Exception as exc:  # noqa: BLE001
        _warn("register_order", exc)

    # documents expansions
    ensure_column("documents", "moa_number", "moa_number VARCHAR(64)")
    ensure_column("documents", "category", "category VARCHAR(64) NOT NULL DEFAULT 'other'")
    ensure_column("documents", "description", "description VARCHAR(255)")
    ensure_column("documents", "stored_bytes", "stored_bytes INTEGER")
    ensure_column(
        "documents",
        "stored_encoding",
        "stored_encoding VARCHAR(16) NOT NULL DEFAULT 'plain'",
    )
    ensure_column("cost_estimate_attachments", "stored_bytes", "stored_bytes INTEGER")
    ensure_column(
        "cost_estimate_attachments",
        "stored_encoding",
        "stored_encoding VARCHAR(16) NOT NULL DEFAULT 'plain'",
    )
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE documents ALTER COLUMN category TYPE VARCHAR(64)"))
    except Exception as exc:  # noqa: BLE001
        _warn("documents.category type", exc)

    # cost estimate expansions (MoA history + attachments)
    ensure_column("cost_estimates", "site_id", "site_id INTEGER REFERENCES sites(id) ON DELETE CASCADE")
    ensure_column("cost_estimates", "notes", "notes TEXT")
    ensure_column("cost_estimates", "moa_number", "moa_number VARCHAR(64)")
    ensure_column("cost_estimates", "summary_total", "summary_total DOUBLE PRECISION")

    # labour rate pack / TMA metadata
    ensure_column("labour_rates", "rate_kind", "rate_kind VARCHAR(32) NOT NULL DEFAULT 'legacy'")
    ensure_column("labour_rates", "pack_people", "pack_people INTEGER NOT NULL DEFAULT 1")
    ensure_column("labour_rates", "includes_vehicle", "includes_vehicle BOOLEAN NOT NULL DEFAULT FALSE")
    ensure_column("labour_rates", "saturday_ordinary", "saturday_ordinary DOUBLE PRECISION NOT NULL DEFAULT 0")
    ensure_column("labour_rates", "saturday_overtime", "saturday_overtime DOUBLE PRECISION NOT NULL DEFAULT 0")
    ensure_column("labour_rates", "sunday_ordinary", "sunday_ordinary DOUBLE PRECISION NOT NULL DEFAULT 0")
    ensure_column("labour_rates", "sunday_overtime", "sunday_overtime DOUBLE PRECISION NOT NULL DEFAULT 0")
    ensure_column(
        "labour_rates",
        "public_holiday_ordinary",
        "public_holiday_ordinary DOUBLE PRECISION NOT NULL DEFAULT 0",
    )
    ensure_column(
        "labour_rates",
        "public_holiday_overtime",
        "public_holiday_overtime DOUBLE PRECISION NOT NULL DEFAULT 0",
    )

    # allowance defaults on cost settings
    ensure_column("cost_settings", "travel_allowance", "travel_allowance DOUBLE PRECISION NOT NULL DEFAULT 45")
    ensure_column("cost_settings", "meal_allowance", "meal_allowance DOUBLE PRECISION NOT NULL DEFAULT 30")
    ensure_column("cost_settings", "meal_after_hours", "meal_after_hours DOUBLE PRECISION NOT NULL DEFAULT 9.5")
    ensure_column("cost_settings", "day_start_hour", "day_start_hour DOUBLE PRECISION NOT NULL DEFAULT 6")
    ensure_column("cost_settings", "day_end_hour", "day_end_hour DOUBLE PRECISION NOT NULL DEFAULT 18")

    # site / council expansions for generic MoA + council SLA
    ensure_column("sites", "is_generic_moa", "is_generic_moa BOOLEAN NOT NULL DEFAULT FALSE")
    ensure_column(
        "sites",
        "linked_generic_moa_id",
        "linked_generic_moa_id INTEGER REFERENCES sites(id) ON DELETE SET NULL",
    )
    ensure_column("site_councils", "submitted_to_council_date", "submitted_to_council_date DATE")
    ensure_column("site_councils", "no_objection_date", "no_objection_date DATE")

    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_sites_archived ON sites (archived)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_sites_financial_year ON sites (financial_year)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_sites_archived_fy ON sites (archived_fy)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_sites_moa_number ON sites (moa_number)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_sites_program ON sites (program)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_moa_number ON documents (moa_number)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_category ON documents (category)"))
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_cost_estimates_moa_number ON cost_estimates (moa_number)")
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_sites_is_generic_moa ON sites (is_generic_moa)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_lookup_items_kind ON lookup_items (kind)"))
    except Exception as exc:  # noqa: BLE001
        _warn("indexes", exc)

    # Seed configurable stages / program categories / settings / lookups
    from .database import SessionLocal
    from .doc_categories import ensure_doc_category_seed
    from .settings_store import ensure_settings
    from .stage_registry import ensure_lookup_seed, ensure_program_seed, ensure_stage_seed

    from .auth import ensure_admin_user, ensure_root_user

    db = SessionLocal()
    try:
        ensure_stage_seed(db)
        ensure_program_seed(db)
        ensure_lookup_seed(db)
        ensure_doc_category_seed(db)
        ensure_settings(db)
        ensure_admin_user(db)
        ensure_root_user(db)
    except Exception as exc:  # noqa: BLE001
        _warn("seed", exc)
    finally:
        db.close()


if __name__ == "__main__":
    run_migrations()
    print("Migrations complete.")
