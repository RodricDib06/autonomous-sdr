"""
People Data Labs (PDL) Enrichment Provider

Free tier: 100 API calls / month — enough for demos and portfolio testing.
Sign up at: https://www.peopledatalabs.com/ → API Keys

PDL enriches a person record from their email address, returning:
  - Full name, job title, seniority
  - Current company + size estimate
  - Industry, location
  - LinkedIn URL, social profiles

Falls back to SyntheticEnrichmentProvider when:
  - PDL returns no match (likelihood < 0.5)
  - The API key is not configured
  - The free tier is exhausted (HTTP 402)

# PRODUCTION notes:
#   - PDL's /person/enrich endpoint also accepts: name, company, profile (LinkedIn URL)
#     Providing more signals improves match likelihood.
#   - For bulk enrichment, use PDL's /bulk/person/enrich endpoint (same cost, fewer round trips).
#   - Cache results by email domain to avoid burning calls on the same company.
#   Docs: https://docs.peopledatalabs.com/docs/person-enrichment-api
"""

import logging
import requests
from app.services.enrichment.base import EnrichmentProvider
from app.services.enrichment.synthetic import SyntheticEnrichmentProvider
from app.config import settings

log = logging.getLogger(__name__)

_PDL_URL = "https://api.peopledatalabs.com/v5/person/enrich"

# PDL seniority labels → our internal labels
_SENIORITY_MAP = {
    "entry":      "Junior",
    "junior":     "Junior",
    "mid":        "Mid-Level",
    "senior":     "Senior",
    "manager":    "Manager",
    "director":   "Director",
    "vp":         "VP",
    "c_suite":    "C-Suite",
    "owner":      "C-Suite",
    "partner":    "VP",
    "unpaid":     "Junior",
    "training":   "Junior",
}

# PDL employee count ranges → our size-range strings
_SIZE_MAP = [
    (10,    "1-10"),
    (50,    "10-50"),
    (200,   "50-200"),
    (500,   "200-500"),
    (1000,  "500-1000"),
    (2000,  "1000-2000"),
    (5000,  "2000-5000"),
    (10000, "5000-10000"),
]


def _map_size(employee_count: int | None) -> str:
    if not employee_count:
        return "50-200"
    for threshold, label in _SIZE_MAP:
        if employee_count <= threshold:
            return label
    return "10000+"


_REVENUE_MAP = {
    "1-10":       "$0-$1M",
    "10-50":      "$1M-$5M",
    "50-200":     "$5M-$20M",
    "200-500":    "$20M-$100M",
    "500-1000":   "$100M-$500M",
    "1000-2000":  "$500M-$1B",
    "2000-5000":  "$1B-$5B",
    "5000-10000": "$5B+",
    "10000+":     "$10B+",
}


class PDLEnrichmentProvider(EnrichmentProvider):
    """
    Enrichment backed by the People Data Labs Person Enrichment API.

    Falls back to SyntheticEnrichmentProvider when PDL has no data or
    the key is exhausted, so the pipeline always produces a result.
    """

    def __init__(self):
        if not settings.PDL_API_KEY:
            raise ValueError("PDL_API_KEY is required for PDLEnrichmentProvider")
        self._fallback = SyntheticEnrichmentProvider()

    def enrich(self, email: str, company: str) -> dict:
        try:
            resp = requests.get(
                _PDL_URL,
                params={
                    "api_key": settings.PDL_API_KEY,
                    "email": email,
                    "pretty": False,
                },
                timeout=8,
            )

            if resp.status_code == 402:
                log.warning("[pdl] Free tier exhausted — falling back to synthetic")
                return self._fallback.enrich(email, company)

            if resp.status_code == 404 or resp.status_code == 200 and resp.json().get("likelihood", 0) < 0.5:
                log.info(f"[pdl] No match for {email} (likelihood too low) — falling back")
                return self._fallback.enrich(email, company)

            resp.raise_for_status()
            data = resp.json()

            # Map PDL fields to our enrichment schema
            (data.get("experience") or [{}])[0] if data.get("experience") else {}
            emp = data.get("job_company_employee_count") or 0
            size_label = _map_size(emp)

            seniority_raw = (data.get("job_title_levels") or [""])[0]
            seniority = _SENIORITY_MAP.get(seniority_raw, "Mid-Level")

            industry = (
                data.get("industry")
                or data.get("job_company_industry")
                or "Technology"
            ).title()

            result = {
                "job_title":        data.get("job_title") or "Unknown",
                "seniority":        seniority,
                "company_size":     size_label,
                "industry":         industry,
                "revenue_estimate": _REVENUE_MAP.get(size_label, "Unknown"),
                "tech_stack":       {},   # PDL doesn't return tech stack; use Hunter or synthetic
                "confidence":       round(data.get("likelihood", 0.5), 2),
                "enrichment_source": "pdl",
            }

            # Optionally surface LinkedIn URL if present
            linkedin = data.get("linkedin_url")
            if linkedin:
                result["linkedin_url"] = linkedin

            log.info(f"[pdl] Enriched {email} → {seniority} at {industry} ({size_label})")
            return result

        except Exception as e:
            log.warning(f"[pdl] API error for {email} ({e}) — falling back to synthetic")
            return self._fallback.enrich(email, company)
