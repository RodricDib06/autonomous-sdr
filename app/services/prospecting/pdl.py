"""
People Data Labs Person Search prospect source.

Uses the Person Search API (a different endpoint from the enrich-by-email
client in enrichment/pdl.py): SQL-style queries over PDL's person dataset,
returning contacts with work emails. Each matched record costs a search
credit — the per-record cost below is recorded on the run so the budget
guardrails and the campaign agent can reason about spend.

Docs: https://docs.peopledatalabs.com/docs/person-search-api
"""

from __future__ import annotations

import logging

import requests

from app.config import settings
from app.services.prospecting.base import ProspectCandidate

log = logging.getLogger(__name__)

_SEARCH_URL = "https://api.peopledatalabs.com/v5/person/search"
_TIMEOUT_SECONDS = 30
# PDL Person Search list price per matched record (pay-as-you-go tier);
# recorded on runs so spend is visible, not silently accumulated
COST_PER_RECORD_USD = 0.28

_SENIORITY_TO_PDL_LEVELS = {
    "c-suite": ["cxo", "owner", "partner"],
    "c-level": ["cxo", "owner", "partner"],
    "vp": ["vp"],
    "director": ["director"],
    "manager": ["manager"],
}


def _build_query(criteria: dict) -> str:
    """SQL-style PDL query from segment criteria. Always requires a work email."""
    clauses = ["work_email IS NOT NULL"]
    if criteria.get("industry"):
        industry = str(criteria["industry"]).replace("'", "")
        clauses.append(f"industry LIKE '%{industry.lower()}%'")
    if criteria.get("seniority"):
        levels = _SENIORITY_TO_PDL_LEVELS.get(str(criteria["seniority"]).lower())
        if levels:
            quoted = ", ".join(f"'{level}'" for level in levels)
            clauses.append(f"job_title_levels IN ({quoted})")
    lo = criteria.get("company_size_min")
    hi = criteria.get("company_size_max")
    if lo is not None or hi is not None:
        # PDL buckets company size; approximate with the employee-count field
        if lo is not None:
            clauses.append(f"job_company_employee_count >= {int(lo)}")
        if hi is not None:
            clauses.append(f"job_company_employee_count <= {int(hi)}")
    return "SELECT * FROM person WHERE " + " AND ".join(clauses)


class PDLProspectSource:
    name = "pdl"

    def search(self, criteria: dict, limit: int) -> list[ProspectCandidate]:
        if not settings.PDL_API_KEY:
            raise RuntimeError("PROSPECTING_PROVIDER=pdl requires PDL_API_KEY")

        resp = requests.post(
            _SEARCH_URL,
            headers={"X-Api-Key": settings.PDL_API_KEY},
            json={"sql": _build_query(criteria or {}), "size": min(limit, 100)},
            timeout=_TIMEOUT_SECONDS,
        )
        if resp.status_code == 404:  # PDL's "no matches" response
            return []
        if not resp.ok:
            raise RuntimeError(f"PDL search returned {resp.status_code}: {resp.text[:300]}")

        candidates: list[ProspectCandidate] = []
        for person in resp.json().get("data", []) or []:
            email = person.get("work_email")
            if not email:
                continue
            first = (person.get("first_name") or "").title()
            last = (person.get("last_name") or "").title()
            candidates.append(ProspectCandidate(
                name=f"{first} {last}".strip() or email.split("@")[0],
                email=email.lower(),
                company=(person.get("job_company_name") or "").title() or email.split("@")[1],
                job_title=(person.get("job_title") or "").title(),
                seniority=(person.get("job_title_levels") or [""])[0].title(),
                industry=(person.get("industry") or "").title(),
                company_size=str(person.get("job_company_employee_count") or ""),
                source="prospecting:pdl",
                cost_usd=COST_PER_RECORD_USD,
                raw={"pdl_id": person.get("id")},
            ))
        return candidates
