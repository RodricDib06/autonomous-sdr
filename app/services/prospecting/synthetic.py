"""
Deterministic demo prospect source.

Generates plausible candidates from the same seeded company universe the
synthetic enrichment provider uses, so the whole prospecting flow demos with
zero API keys — consistent with the platform's zero-cost demo story.

Determinism matters: the same criteria always produce the same candidates
(seeded PRNG), so demos are reproducible and tests don't flake.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

from app.services.prospecting.base import ProspectCandidate

_DOMAINS_PATH = Path(__file__).parent.parent.parent.parent / "data" / "company_domains.json"

with open(_DOMAINS_PATH) as f:
    KNOWN_DOMAINS: dict = json.load(f)

_FIRST_NAMES = [
    "Ava", "Liam", "Maya", "Noah", "Zoe", "Ethan", "Lena", "Owen", "Ines",
    "Felix", "Nora", "Hugo", "Sara", "Adam", "Lucia", "Marco", "Emma", "Jonas",
]
_LAST_NAMES = [
    "Keller", "Mora", "Tanaka", "Novak", "Silva", "Haddad", "Berg", "Costa",
    "Dubois", "Fischer", "Rossi", "Larsen", "Marsh", "Iqbal", "Weber", "Devi",
]

_TITLES_BY_SENIORITY = {
    "C-Suite": ["CTO", "CEO", "CRO", "COO"],
    "VP": ["VP of Engineering", "VP of Sales", "VP of Product"],
    "Director": ["Director of Engineering", "Director of Revenue Operations"],
    "Manager": ["Engineering Manager", "Sales Operations Manager"],
}
_DEFAULT_SENIORITIES = ["VP", "Director", "Manager", "C-Suite"]


def _size_midpoint(size_range: str) -> int:
    from app.services.icp_service import parse_company_size
    return parse_company_size(size_range) or 0


class SyntheticProspectSource:
    name = "synthetic"

    def search(self, criteria: dict, limit: int) -> list[ProspectCandidate]:
        criteria = criteria or {}
        seed = hashlib.sha256(
            json.dumps(criteria, sort_keys=True).encode()
        ).hexdigest()
        rng = random.Random(seed)

        # Filter the company universe by criteria first
        domains = []
        for domain, info in sorted(KNOWN_DOMAINS.items()):
            if criteria.get("industry") and criteria["industry"].lower() not in info["industry"].lower():
                continue
            midpoint = _size_midpoint(info["size_range"])
            if criteria.get("company_size_min") is not None and midpoint < criteria["company_size_min"]:
                continue
            if criteria.get("company_size_max") is not None and midpoint > criteria["company_size_max"]:
                continue
            domains.append((domain, info))

        seniorities = (
            [criteria["seniority"]] if criteria.get("seniority") else _DEFAULT_SENIORITIES
        )

        candidates: list[ProspectCandidate] = []
        while len(candidates) < limit and domains:
            domain, info = domains[len(candidates) % len(domains)]
            first = rng.choice(_FIRST_NAMES)
            last = rng.choice(_LAST_NAMES)
            seniority = rng.choice(seniorities)
            titles = _TITLES_BY_SENIORITY.get(seniority, ["Manager"])
            company = domain.split(".")[0].capitalize()
            candidates.append(ProspectCandidate(
                name=f"{first} {last}",
                email=f"{first.lower()}.{last.lower()}@{domain}",
                company=company,
                job_title=rng.choice(titles),
                seniority=seniority,
                industry=info["industry"],
                company_size=info["size_range"],
                source="prospecting:synthetic",
                cost_usd=0.0,
                raw={"domain": domain},
            ))
        return candidates
