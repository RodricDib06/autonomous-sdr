import logging
import requests
from app.config import settings
from app.services.enrichment.base import EnrichmentProvider
from app.services.enrichment.synthetic import (
    SyntheticEnrichmentProvider,
    SENIORITY_LEVELS,
    SENIORITY_WEIGHTS,
    JOB_TITLES_BY_SENIORITY,
    TECH_STACKS,
    SIZE_TO_REVENUE,
)
import random

log = logging.getLogger(__name__)

_HUNTER_API = "https://api.hunter.io/v2/domain-search"

# Map Hunter email count to a company size range
_COUNT_TO_SIZE = [
    (10,   "1-10"),
    (50,   "10-50"),
    (200,  "50-200"),
    (500,  "200-500"),
    (1000, "500-1000"),
    (2000, "1000-2000"),
    (5000, "2000-5000"),
]


def _size_from_email_count(count: int) -> str:
    for threshold, label in _COUNT_TO_SIZE:
        if count <= threshold:
            return label
    return "5000-10000"


class HunterEnrichmentProvider(EnrichmentProvider):
    """Enrichment backed by the Hunter.io domain-search API.

    Falls back to SyntheticEnrichmentProvider when Hunter has no data for a
    domain (private companies, very small businesses) so the pipeline always
    produces a result.

    Free tier: 25 domain searches / month — enough for demos and pitches.
    """

    def __init__(self):
        if not settings.HUNTER_API_KEY:
            raise ValueError(
                "HUNTER_API_KEY is not set. "
                "Add it to your .env file to use ENRICHMENT_PROVIDER=hunter."
            )
        self._api_key = settings.HUNTER_API_KEY
        self._fallback = SyntheticEnrichmentProvider()
        self._cache: dict = {}

    def enrich(self, email: str, company: str) -> dict:
        domain = email.split("@")[-1].lower().strip()

        if domain in self._cache:
            company_data = self._cache[domain]
        else:
            company_data = self._fetch_domain(domain)
            self._cache[domain] = company_data

        if not company_data:
            log.debug(f"Hunter found no data for {domain}, falling back to synthetic")
            return self._fallback.enrich(email, company)

        # Per-person fields stay synthetic — Hunter gives company data, not individual
        seniority = random.choices(SENIORITY_LEVELS, SENIORITY_WEIGHTS)[0]
        job_title = random.choice(JOB_TITLES_BY_SENIORITY[seniority])
        tech_stack = (
            company_data.get("technologies")[:6]
            if company_data.get("technologies")
            else random.choice(TECH_STACKS)
        )

        size_range = company_data.get("size_range", "50-200")
        revenue_estimate = SIZE_TO_REVENUE.get(size_range, "$5M-$20M")

        return {
            "job_title": job_title,
            "seniority": seniority,
            "company_size": size_range,
            "industry": company_data.get("industry") or "Technology",
            "revenue_estimate": revenue_estimate,
            "tech_stack": tech_stack,
            "confidence": company_data.get("confidence", 0.8),
            "enrichment_source": "hunter_io_v2",
        }

    def _fetch_domain(self, domain: str) -> dict | None:
        try:
            resp = requests.get(
                _HUNTER_API,
                params={"domain": domain, "limit": 3, "api_key": self._api_key},
                timeout=10,
            )
            if resp.status_code == 401:
                raise ValueError("Hunter.io API key is invalid or expired.")
            if resp.status_code == 429:
                log.warning("Hunter.io rate limit hit — falling back to synthetic")
                return None
            if not resp.ok:
                log.warning(f"Hunter.io returned {resp.status_code} for {domain}")
                return None

            data = resp.json().get("data", {})
            if not data:
                return None

            # Derive size from total email count Hunter has indexed for this domain
            email_count = resp.json().get("meta", {}).get("results", 0)
            size_range = _size_from_email_count(email_count)

            return {
                "industry": data.get("industry"),
                "size_range": size_range,
                "technologies": data.get("technologies", []),
                "confidence": 0.85,
            }

        except ValueError:
            raise
        except Exception as e:
            log.warning(f"Hunter.io request failed for {domain}: {e}")
            return None
