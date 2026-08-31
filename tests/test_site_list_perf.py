"""Register list stays cheap when many jobs have documents / estimates."""

from datetime import datetime, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import CostEstimate, Document, ProgramCategory, Site
from app.routers.sites import _base_query
from app.services import serialize_sites
from app.settings_store import ensure_settings
from app.stage_registry import ensure_stage_seed


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def _site(db, name, no, program="Structures"):
    now = datetime.now(timezone.utc)
    site = Site(
        road_name=name,
        site_number=no,
        program=program,
        created_at=now,
        updated_at=now,
        custom_fields={},
        tags=[],
    )
    db.add(site)
    db.flush()
    return site


def test_list_query_does_not_fetch_document_rows():
    engine, db = _session()
    site = _site(db, "BALLARAT RD", "S1")
    db.add(
        Document(
            site_id=site.id,
            stored_name="a.bin",
            original_filename="a.pdf",
            size_bytes=10,
        )
    )
    db.commit()
    statements: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _capture)
    loaded = _base_query(db, archived=False).all()
    event.remove(engine, "before_cursor_execute", _capture)
    assert len(loaded) == 1
    joined = " ".join(statements).lower()
    assert "from documents" not in joined
    assert "from cost_estimates" not in joined
    assert "from map_features" not in joined
    # noload presents an empty collection; counts come from a later GROUP BY.
    assert list(loaded[0].documents) == []


def test_serialize_sites_uses_counts_and_cached_category_tags():
    engine, db = _session()
    ensure_stage_seed(db)
    ensure_settings(db)
    db.add(ProgramCategory(name="Structures", position=10, active=True, tags=["structures"]))
    sites = [_site(db, f"ROAD {i}", f"S{i}") for i in range(6)]
    for site in sites:
        for n in range(4):
            db.add(
                Document(
                    site_id=site.id,
                    stored_name=f"{site.id}-{n}.bin",
                    original_filename=f"{n}.pdf",
                    size_bytes=1,
                )
            )
        db.add(
            CostEstimate(
                site_id=site.id,
                name="quote",
                mode="standard",
                summary_total=100.0 + site.id,
                inputs={},
                results={},
                created_at=datetime.now(timezone.utc),
            )
        )
    db.commit()

    statements: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _capture)
    rows = serialize_sites(db, _base_query(db, archived=False).all())
    event.remove(engine, "before_cursor_execute", _capture)

    assert len(rows) == 6
    assert all(row["document_count"] == 4 for row in rows)
    assert all(row["cost_estimate_count"] == 1 for row in rows)
    assert all(row["latest_cost_total"] == 100.0 + row["id"] for row in rows)
    assert rows[0]["category_tags"] == ["structures"]
    assert "structures" in rows[0]["effective_tags"]
    program_scans = sum(1 for sql in statements if "program_categories" in sql.lower())
    assert program_scans <= 2
    assert len(statements) < 20
    assert sum(1 for sql in statements if "from documents" in sql.lower() and "count(" in sql.lower()) == 1
    assert sum(1 for sql in statements if "from documents" in sql.lower() and "count(" not in sql.lower()) == 0
