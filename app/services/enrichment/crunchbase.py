"""
Crunchbase Enrichment / Intent Signal Provider

Crunchbase data surfaces two high-value signals for intent scoring:
  1. Recent funding — a company that raised in the last 6 months almost
     certainly has budget and is actively buying new tools.
  2. Growth trajectory — headcount growth signals expansion intent.

PoC: mock implementation that returns plausible synthetic data so the
     rest of the pipeline (intent scoring, BANT analysis) works end-to-end.
     The mock is structured identically to what the real API returns so
     swapping in production credentials requires only removing the mock block.

# PRODUCTION Crunchbase Basic API ($29/month):
#   Sign up at: https://data.crunchbase.com/docs/crunchbase-basic-getting-started
#   API key from: https://www.crunchbase.com/account/api
#
#   Lookup organisation by domain:
#     GET https://api.crunchbase.com/api/v4/entities/organizations/{permalink}
#         ?card_ids=funding_rounds,employees
#         &field_ids=short_description,num_employees_enum,last_funding_type,last_funding_total
#         &user_key={CRUNCHBASE_API_KEY}
#
#   Find permalink from domain (requires Basic+):
#     GET https://api.crunchbase.com/api/v4/autocompletes
#         ?query={company_name}&collection_ids=organizations&user_key={key}
#
#   Relevant response fields:
#     properties.last_funding_type:   "series_a" | "series_b" | "seed" | "ipo" | ...
#     properties.last_funding_total:  {value_usd: 5000000}
#     cards.funding_rounds[0].announced_on: "2024-11-01"
#     properties.num_employees_enum:  "c_1_10" | "c_11_50" | "c_51_200" | ...
#
#   Python example (real):
#     import requests
#     from datetime import datetime, timedelta
#     resp = requests.get(
#         f"https://api.crunchbase.com/api/v4/entities/organizations/{permalink}",
#         params={"field_ids": "last_funding_type,last_funding_total",
#                 "card_ids": "funding_rounds",
#                 "user_key": settings.CRUNCHBASE_API_KEY},
#         timeout=8,
#     )
#     data = resp.json()["properties"]
#     rounds = resp.json().get("cards", {}).get("funding_rounds", [])
#     recent = [r for r in rounds if r.get("announced_on")
#               and datetime.fromisoformat(r["announced_on"]) > datetime.now() - timedelta(days=180)]
#     return {"recent_funding": bool(recent), "funding_type": data.get("last_funding_type")}
"""

import logging
import random
from datetime import timedelta
from app.config import settings
from app.utils.time import utcnow

log = logging.getLogger(__name__)


def get_funding_signals(company: str, domain: str | None = None) -> dict:
    """
    Return funding and growth signals for a company.

    Returns:
      {
        "recent_funding": bool,          # raised money in last 6 months
        "funding_type": str | None,      # "seed" | "series_a" | "series_b" | ...
        "funding_amount_usd": int | None,
        "announced_on": str | None,      # ISO date
        "headcount_growth_6m": float,    # e.g. 0.15 = 15% headcount growth
        "source": "crunchbase" | "mock",
      }
    """
    if settings.CRUNCHBASE_API_KEY:
        return _real_crunchbase(company, domain)
    else:
        return _mock_signals(company)


def _real_crunchbase(company: str, domain: str | None) -> dict:
    """
    Call the real Crunchbase API.

    # PRODUCTION: replace the mock block below with real HTTP calls.
    #   1. Resolve domain → permalink via autocomplete endpoint
    #   2. Fetch organisation entity with funding_rounds card
    #   3. Check if any round was announced in last 180 days
    #
    # import requests
    # from datetime import datetime, timedelta
    #
    # def _resolve_permalink(company: str, key: str) -> str | None:
    #     resp = requests.get(
    #         "https://api.crunchbase.com/api/v4/autocompletes",
    #         params={"query": company, "collection_ids": "organizations", "user_key": key},
    #         timeout=5,
    #     )
    #     entities = resp.json().get("entities", [])
    #     return entities[0]["identifier"]["permalink"] if entities else None
    #
    # permalink = _resolve_permalink(company, settings.CRUNCHBASE_API_KEY)
    # if not permalink:
    #     return _mock_signals(company)
    #
    # resp = requests.get(
    #     f"https://api.crunchbase.com/api/v4/entities/organizations/{permalink}",
    #     params={"field_ids": "last_funding_type,last_funding_total",
    #             "card_ids": "funding_rounds", "user_key": settings.CRUNCHBASE_API_KEY},
    #     timeout=8,
    # )
    # data = resp.json()
    # props = data.get("properties", {})
    # rounds = data.get("cards", {}).get("funding_rounds", [])
    # cutoff = datetime.now() - timedelta(days=180)
    # recent = [r for r in rounds
    #           if r.get("announced_on") and
    #           datetime.fromisoformat(r["announced_on"]) > cutoff]
    # return {
    #     "recent_funding":     bool(recent),
    #     "funding_type":       props.get("last_funding_type"),
    #     "funding_amount_usd": (props.get("last_funding_total") or {}).get("value_usd"),
    #     "announced_on":       recent[0]["announced_on"] if recent else None,
    #     "headcount_growth_6m": 0.0,  # not available in Basic tier
    #     "source":             "crunchbase",
    # }
    """
    log.info(f"[crunchbase] API key set but real call not yet wired — using mock for {company}")
    return _mock_signals(company)


def _mock_signals(company: str) -> dict:
    """
    Deterministic-ish mock: seed random from company name so the same
    company always gets the same signals across runs.
    """
    rng = random.Random(hash(company) % (2**32))

    # ~30% of companies have recent funding in demo data
    recent_funding = rng.random() < 0.30
    funding_types = ["seed", "series_a", "series_b", "series_c", None, None, None]
    funding_type = rng.choice(funding_types) if recent_funding else None

    # Funding amounts by round type
    amounts = {
        "seed":     rng.randint(500_000,   3_000_000),
        "series_a": rng.randint(3_000_000, 15_000_000),
        "series_b": rng.randint(15_000_000, 50_000_000),
        "series_c": rng.randint(50_000_000, 200_000_000),
    }

    announced_on = None
    if recent_funding:
        days_ago = rng.randint(10, 170)
        announced_on = (utcnow() - timedelta(days=days_ago)).date().isoformat()

    return {
        "recent_funding":     recent_funding,
        "funding_type":       funding_type,
        "funding_amount_usd": amounts.get(funding_type) if funding_type else None,
        "announced_on":       announced_on,
        "headcount_growth_6m": round(rng.uniform(-0.05, 0.30), 2),
        "source":             "mock",
    }
