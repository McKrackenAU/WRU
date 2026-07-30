"""Lightweight schema upgrade for existing PostgreSQL databases."""

from __future__ import annotations

from sqlalchemy import inspect, text

from .database import Base, engine
from .models import (  # noqa: F401 — register metadata
    CostEstimate,
    CostEstimateAttachment,
    CostSettings,
    CustomColumn,
    Document,
    LabourRate,
    MapFeature,
    MapLayer,
    ProgramCategory,
    Site,
    SiteCouncil,
    TrackingEvent,
    WorkflowStageDef,
    WorkflowStep,
)


def column_names(table: str) -> set[str]:
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def ensure_column(table: str, column: str, ddl: str) -> None:
    if column in column_names(table):
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))


def run_migrations() -> None:
    Base.metadata.create_all(bind=engine)

    # sites expansions
    ensure_column("sites", "program", "program VARCHAR(128)")
    ensure_column("sites", "tgs_reference", "tgs_reference VARCHAR(128)")
    ensure_column("sites", "financial_year", "financial_year VARCHAR(16)")
    ensure_column("sites", "archived", "archived BOOLEAN NOT NULL DEFAULT FALSE")
    ensure_column("sites", "archived_at", "archived_at TIMESTAMPTZ")
    ensure_column("sites", "archived_fy", "archived_fy VARCHAR(16)")

    # documents expansions
    ensure_column("documents", "moa_number", "moa_number VARCHAR(64)")
    ensure_column("documents", "category", "category VARCHAR(32) NOT NULL DEFAULT 'other'")
    ensure_column("documents", "description", "description VARCHAR(255)")

    # cost estimate expansions (MoA history + attachments)
    ensure_column("cost_estimates", "site_id", "site_id INTEGER REFERENCES sites(id) ON DELETE CASCADE")
    ensure_column("cost_estimates", "notes", "notes TEXT")
    ensure_column("cost_estimates", "moa_number", "moa_number VARCHAR(64)")
    ensure_column("cost_estimates", "summary_total", "summary_total DOUBLE PRECISION")

    # labour rate pack / TMA metadata
    ensure_column("labour_rates", "rate_kind", "rate_kind VARCHAR(32) NOT NULL DEFAULT 'legacy'")
    ensure_column("labour_rates", "pack_people", "pack_people INTEGER NOT NULL DEFAULT 1")
    ensure_column("labour_rates", "includes_vehicle", "includes_vehicle BOOLEAN NOT NULL DEFAULT FALSE")

    # allowance defaults on cost settings
    ensure_column("cost_settings", "travel_allowance", "travel_allowance DOUBLE PRECISION NOT NULL DEFAULT 45")
    ensure_column("cost_settings", "meal_allowance", "meal_allowance DOUBLE PRECISION NOT NULL DEFAULT 30")
    ensure_column("cost_settings", "meal_after_hours", "meal_after_hours DOUBLE PRECISION NOT NULL DEFAULT 9.5")

    # site / council expansions for generic MoA + council SLA
    ensure_column("sites", "is_generic_moa", "is_generic_moa BOOLEAN NOT NULL DEFAULT FALSE")
    ensure_column(
        "sites",
        "linked_generic_moa_id",
        "linked_generic_moa_id INTEGER REFERENCES sites(id) ON DELETE SET NULL",
    )
    ensure_column("site_councils", "submitted_to_council_date", "submitted_to_council_date DATE")
    ensure_column("site_councils", "no_objection_date", "no_objection_date DATE")

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

    # Seed configurable stages / program categories
    from .database import SessionLocal
    from .stage_registry import ensure_program_seed, ensure_stage_seed

    db = SessionLocal()
    try:
        ensure_stage_seed(db)
        ensure_program_seed(db)
    finally:
        db.close()


if __name__ == "__main__":
    run_migrations()
    print("Migrations complete.")
