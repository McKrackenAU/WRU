"""Lightweight schema upgrade for existing PostgreSQL databases."""

from __future__ import annotations

from sqlalchemy import inspect, text

from .database import Base, engine
from .models import (  # noqa: F401 — register metadata
    CostEstimate,
    CostSettings,
    CustomColumn,
    Document,
    LabourRate,
    MapFeature,
    MapLayer,
    Site,
    SiteCouncil,
    TrackingEvent,
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

    with engine.begin() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_sites_archived ON sites (archived)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_sites_financial_year ON sites (financial_year)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_sites_archived_fy ON sites (archived_fy)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_sites_moa_number ON sites (moa_number)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_sites_program ON sites (program)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_moa_number ON documents (moa_number)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_category ON documents (category)"))


if __name__ == "__main__":
    run_migrations()
    print("Migrations complete.")
