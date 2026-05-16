"""Tests for export_service formatting functions."""
import csv
import io
from datetime import datetime
from unittest.mock import MagicMock

from app.services.export_service import (
    build_export_rows,
    to_csv_bytes,
    to_hubspot_rows,
    to_salesforce_rows,
)


def _mock_lead(name="Alice Wong", email="alice@acme.com", company="Acme",
               verdict="Hot", confidence=0.9, job_title="VP Sales",
               industry="SaaS", tags=None):
    """Build a minimal mock Lead object."""
    enrichment = MagicMock()
    enrichment.job_title = job_title
    enrichment.seniority = "VP"
    enrichment.company_size = "51-200"
    enrichment.industry = industry
    enrichment.revenue_estimate = "$5M-$10M"

    v = MagicMock()
    v.final_verdict = verdict
    v.confidence_score = confidence
    v.bant_scores = {"budget": 4, "authority": 5, "need": 4, "timeline": 3}
    v.icp_match = True
    v.analysis_reasoning = "Strong fit"

    lead = MagicMock()
    lead.id = "abc-123"
    lead.name = name
    lead.email = email
    lead.company = company
    lead.enrichments = [enrichment]
    lead.verdicts = [v]
    lead.tags = tags or []
    lead.archived = False
    lead.data_quality_score = 88.0
    lead.created_at = datetime(2026, 1, 15)
    return lead


# ---------------------------------------------------------------------------
# build_export_rows
# ---------------------------------------------------------------------------

def test_build_export_rows_keys():
    rows = build_export_rows([_mock_lead()])
    assert len(rows) == 1
    row = rows[0]
    for key in ("id", "name", "email", "company", "job_title", "verdict", "confidence_score"):
        assert key in row


def test_build_export_rows_no_enrichment():
    lead = _mock_lead()
    lead.enrichments = []
    lead.verdicts = []
    rows = build_export_rows([lead])
    assert rows[0]["job_title"] is None
    assert rows[0]["verdict"] is None


def test_build_export_rows_empty():
    assert build_export_rows([]) == []


# ---------------------------------------------------------------------------
# to_csv_bytes
# ---------------------------------------------------------------------------

def test_to_csv_bytes_roundtrip():
    rows = build_export_rows([_mock_lead(name="Bob", email="bob@corp.com", company="Corp")])
    raw = to_csv_bytes(rows)
    assert isinstance(raw, bytes)
    reader = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    assert len(reader) == 1
    assert reader[0]["name"] == "Bob"
    assert reader[0]["email"] == "bob@corp.com"


def test_to_csv_bytes_empty():
    assert to_csv_bytes([]) == b""


def test_to_csv_bytes_multiple_rows():
    leads = [_mock_lead(name=f"User {i}", email=f"u{i}@co.com", company="Co") for i in range(5)]
    rows = build_export_rows(leads)
    raw = to_csv_bytes(rows)
    reader = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    assert len(reader) == 5


# ---------------------------------------------------------------------------
# to_hubspot_rows
# ---------------------------------------------------------------------------

def test_hubspot_renames_email_key():
    rows = build_export_rows([_mock_lead()])
    hs = to_hubspot_rows(rows)
    assert "Email" in hs[0]
    assert "email" not in hs[0]


def test_hubspot_renames_company_key():
    rows = build_export_rows([_mock_lead()])
    hs = to_hubspot_rows(rows)
    assert "Company" in hs[0]


def test_hubspot_verdict_maps_to_lead_status():
    rows = build_export_rows([_mock_lead(verdict="Hot")])
    hs = to_hubspot_rows(rows)
    assert hs[0]["Lead Status"] == "Hot"


# ---------------------------------------------------------------------------
# to_salesforce_rows
# ---------------------------------------------------------------------------

def test_salesforce_renames_email_key():
    rows = build_export_rows([_mock_lead()])
    sf = to_salesforce_rows(rows)
    assert "Email" in sf[0]


def test_salesforce_splits_name():
    rows = build_export_rows([_mock_lead(name="Alice Wong")])
    sf = to_salesforce_rows(rows)
    assert sf[0]["FirstName"] == "Alice"
    assert sf[0]["LastName"] == "Wong"


def test_salesforce_single_name():
    rows = build_export_rows([_mock_lead(name="Madonna")])
    sf = to_salesforce_rows(rows)
    assert sf[0]["FirstName"] == ""
    assert sf[0]["LastName"] == "Madonna"


def test_salesforce_job_title_maps_to_title():
    rows = build_export_rows([_mock_lead(job_title="CTO")])
    sf = to_salesforce_rows(rows)
    assert sf[0]["Title"] == "CTO"
