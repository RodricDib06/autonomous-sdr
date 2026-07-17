"""Prospect source contract — every provider returns the same candidate shape."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ProspectCandidate:
    name: str
    email: str
    company: str
    job_title: str = ""
    seniority: str = ""
    industry: str = ""
    company_size: str = ""
    source: str = "prospecting"
    # Per-record data cost in USD (None when the provider is free)
    cost_usd: float | None = None
    raw: dict = field(default_factory=dict)


class ProspectSource(Protocol):
    name: str

    def search(self, criteria: dict, limit: int) -> list[ProspectCandidate]:
        """criteria: {industry?, seniority?, company_size_min?, company_size_max?}"""
        ...
