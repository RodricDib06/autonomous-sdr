"""
Export formatting service.

Pure functions — no DB access. Takes pre-loaded Lead ORM objects and produces
various output formats for download or CRM ingestion.
"""
from __future__ import annotations

import csv
import io
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.database.models import Lead


def build_export_rows(leads: list["Lead"]) -> list[dict]:
    """Assemble canonical export dicts from Lead ORM objects."""
    rows = []
    for lead in leads:
        verdict = lead.verdicts[0] if lead.verdicts else None
        enrichment = lead.enrichments[0] if lead.enrichments else None
        rows.append({
            "id": lead.id,
            "name": lead.name,
            "email": lead.email,
            "company": lead.company,
            "job_title": enrichment.job_title if enrichment else None,
            "seniority": enrichment.seniority if enrichment else None,
            "company_size": enrichment.company_size if enrichment else None,
            "industry": enrichment.industry if enrichment else None,
            "revenue_estimate": enrichment.revenue_estimate if enrichment else None,
            "verdict": verdict.final_verdict if verdict else None,
            "confidence_score": verdict.confidence_score if verdict else None,
            "bant_budget": verdict.bant_scores.get("budget") if verdict and verdict.bant_scores else None,
            "bant_authority": verdict.bant_scores.get("authority") if verdict and verdict.bant_scores else None,
            "bant_need": verdict.bant_scores.get("need") if verdict and verdict.bant_scores else None,
            "bant_timeline": verdict.bant_scores.get("timeline") if verdict and verdict.bant_scores else None,
            "icp_match": verdict.icp_match if verdict else None,
            "reasoning": verdict.analysis_reasoning if verdict else None,
            "tags": ",".join(lead.tags) if lead.tags else None,
            "archived": lead.archived,
            "data_quality_score": lead.data_quality_score,
            "processed_at": lead.created_at.isoformat() if lead.created_at else None,
        })
    return rows


def to_csv_bytes(rows: list[dict]) -> bytes:
    """Serialize rows to UTF-8 CSV bytes."""
    if not rows:
        return b""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# HubSpot column mapping
# ---------------------------------------------------------------------------
_HUBSPOT_MAP = {
    "id": "Lead ID",
    "name": "Full Name",
    "email": "Email",
    "company": "Company",
    "job_title": "Job Title",
    "seniority": "Seniority Level",
    "company_size": "Number of Employees",
    "industry": "Industry",
    "revenue_estimate": "Annual Revenue",
    "verdict": "Lead Status",
    "confidence_score": "Lead Score",
    "icp_match": "ICP Match",
    "tags": "Tags",
    "data_quality_score": "Data Quality Score",
    "processed_at": "Create Date",
}


def to_hubspot_rows(rows: list[dict]) -> list[dict]:
    """Re-key canonical rows to HubSpot column names (unmapped fields dropped)."""
    result = []
    for row in rows:
        result.append({_HUBSPOT_MAP[k]: v for k, v in row.items() if k in _HUBSPOT_MAP})
    return result


# ---------------------------------------------------------------------------
# Salesforce column mapping
# ---------------------------------------------------------------------------
_SALESFORCE_MAP = {
    "id": "Id",
    "email": "Email",
    "company": "Company",
    "job_title": "Title",
    "seniority": "Seniority__c",
    "company_size": "NumberOfEmployees",
    "industry": "Industry",
    "revenue_estimate": "AnnualRevenue",
    "verdict": "LeadSource",
    "confidence_score": "Rating",
    "icp_match": "ICP_Match__c",
    "tags": "Tags__c",
    "data_quality_score": "Data_Quality_Score__c",
    "processed_at": "CreatedDate",
}


def to_salesforce_rows(rows: list[dict]) -> list[dict]:
    """Re-key canonical rows to Salesforce column names, splitting name into FirstName/LastName."""
    result = []
    for row in rows:
        sf = {_SALESFORCE_MAP[k]: v for k, v in row.items() if k in _SALESFORCE_MAP}
        # Split full name
        name = row.get("name") or ""
        parts = name.split(" ", 1)
        sf["FirstName"] = parts[0] if len(parts) > 1 else ""
        sf["LastName"] = parts[-1]
        result.append(sf)
    return result
