"""
Real-Postgres integration tests: exercise the JSONB operators and schema
constraints that the SQLite unit suite structurally cannot cover.
"""

import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


def _models():
    from app.database.models import Lead, Organization, SuppressionEntry, Verdict
    return Lead, Organization, SuppressionEntry, Verdict


def _lead(org_id=None, **kw):
    Lead, *_ = _models()
    defaults = dict(name="IT Lead", email=f"it-{uuid.uuid4().hex[:8]}@test.com", company="ITCo")
    defaults.update(kw)
    return Lead(org_id=org_id, **defaults)


def test_migrations_created_new_tables(pg_raw):
    tables = {
        r[0]
        for r in pg_raw.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
        ))
    }
    expected = {
        "organizations", "suppression_list", "sending_mailboxes",
        "llm_calls", "gdpr_erasures", "outreach_emails", "leads",
    }
    missing = expected - tables
    assert not missing, f"Missing tables (run alembic upgrade head): {missing}"


def test_jsonb_tags_contains(pg_db):
    """The demo-seeder guard uses tags.contains(['demo']) — a JSONB @> query."""
    lead = _lead(tags=["demo", "test"])
    pg_db.add(lead)
    pg_db.add(_lead(tags=["other"]))
    pg_db.flush()

    Lead, *_ = _models()
    found = pg_db.query(Lead).filter(Lead.tags.contains(["demo"])).all()
    assert lead.id in {ld.id for ld in found}
    assert all("demo" in (ld.tags or []) for ld in found)


def test_jsonb_bant_astext_filter(pg_db):
    """The /leads list BANT filters use bant_scores[dim].astext."""
    Lead, _, _, Verdict = _models()
    lead = _lead()
    pg_db.add(lead)
    pg_db.flush()
    pg_db.add(Verdict(lead_id=lead.id, final_verdict="Hot",
                      bant_scores={"authority": "High", "budget": "Medium"}))
    pg_db.flush()

    rows = (
        pg_db.query(Lead)
        .join(Verdict, Verdict.lead_id == Lead.id)
        .filter(Verdict.bant_scores["authority"].astext == "High")
        .all()
    )
    assert lead.id in {ld.id for ld in rows}


def test_suppression_unique_per_org(pg_db):
    """(org_id, value) unique index: same value in two orgs OK, dupe in one org fails."""
    _, Organization, SuppressionEntry, _ = _models()

    org_a = Organization(name="IT A", slug=f"it-a-{uuid.uuid4().hex[:8]}")
    org_b = Organization(name="IT B", slug=f"it-b-{uuid.uuid4().hex[:8]}")
    pg_db.add_all([org_a, org_b])
    pg_db.flush()

    pg_db.add(SuppressionEntry(value="dup@x.com", kind="email", org_id=org_a.id))
    pg_db.add(SuppressionEntry(value="dup@x.com", kind="email", org_id=org_b.id))
    pg_db.flush()  # two orgs, same value — allowed

    pg_db.add(SuppressionEntry(value="dup@x.com", kind="email", org_id=org_a.id))
    with pytest.raises(Exception):
        pg_db.flush()


def test_timezone_column_roundtrip(pg_db):
    lead = _lead(timezone="Europe/Berlin")
    pg_db.add(lead)
    pg_db.flush()
    pg_db.refresh(lead)
    assert lead.timezone == "Europe/Berlin"
