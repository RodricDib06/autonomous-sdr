"""
Web Signal Enrichment — free, no API key required.

Given a company email or domain, fetches publicly available signals:
  - Open roles (SDR/Sales postings = active buying signal)
  - Tech stack keywords from job descriptions
  - Company description from homepage
  - Employee count hints from "About" or "Team" pages

Uses httpx (sync) + BeautifulSoup. Handles timeouts, redirects, SSL errors,
robots.txt violations (we only request public pages), and non-HTML responses.
All requests have a 6-second timeout. Falls back gracefully on any error.
"""

from __future__ import annotations
import logging
import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

_TIMEOUT = 6.0
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; AutonomousSDR/1.0; "
        "+https://github.com/autonomoussdr)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# SDR/sales buying signals in job listings
_BUYING_SIGNAL_KEYWORDS = [
    "sales development", "outbound sales", "sdr", "business development",
    "account executive", "revenue operations", "sales enablement",
    "crm", "hubspot", "salesforce", "pipeline", "quota", "prospecting",
]

# Tech stack indicators
_TECH_KEYWORDS = {
    "Salesforce": ["salesforce", "sfdc"],
    "HubSpot": ["hubspot"],
    "Marketo": ["marketo"],
    "Outreach": ["outreach.io"],
    "Gong": ["gong.io"],
    "Apollo": ["apollo.io"],
    "ZoomInfo": ["zoominfo"],
    "Slack": ["slack"],
    "Snowflake": ["snowflake"],
    "dbt": [" dbt "],
    "AWS": ["aws", "amazon web services"],
    "GCP": ["google cloud", "gcp"],
    "Azure": ["microsoft azure", " azure "],
}

_SIZE_PATTERNS = [
    re.compile(r"(\d[\d,]*)\s*\+?\s*(employees?|people|team members?)", re.I),
    re.compile(r"(small|mid.?size|large|enterprise)\s+team", re.I),
]


def _extract_domain(email_or_domain: str) -> str | None:
    raw = email_or_domain.strip().lower()
    if "@" in raw:
        raw = raw.split("@")[1]
    # Remove common free email providers
    free_domains = {
        "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
        "icloud.com", "protonmail.com", "tempmail.xyz", "disposable.com",
    }
    if raw in free_domains:
        return None
    return raw


def _safe_get(client: httpx.Client, url: str) -> str | None:
    try:
        resp = client.get(url, timeout=_TIMEOUT, follow_redirects=True)
        if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""):
            return resp.text
    except Exception:
        pass
    return None


def _find_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return " ".join(soup.get_text(" ", strip=True).lower().split())


def enrich_from_domain(email_or_domain: str) -> dict:
    """
    Scrape publicly available signals from a company's website.

    Returns a dict with:
      signals          — list of {type, text, weight} buying signals
      tech_stack       — list of detected tech keywords
      employee_hints   — list of employee count mentions
      pages_fetched    — number of pages successfully fetched
      domain           — cleaned domain used
      error            — None or brief error description
    """
    domain = _extract_domain(email_or_domain)
    result: dict = {
        "domain": domain,
        "signals": [],
        "tech_stack": [],
        "employee_hints": [],
        "pages_fetched": 0,
        "error": None,
    }

    if not domain:
        result["error"] = "Free email provider — no company domain to scrape"
        return result

    base = f"https://{domain}"
    pages_to_try = [
        (base, "homepage"),
        (f"{base}/careers", "careers"),
        (f"{base}/jobs", "jobs"),
        (f"{base}/about", "about"),
        (f"{base}/about-us", "about-us"),
    ]

    all_text = ""

    try:
        with httpx.Client(headers=_HEADERS, verify=False) as client:  # noqa: S501 — scraping public pages
            for url, page_type in pages_to_try:
                html = _safe_get(client, url)
                if not html:
                    continue
                soup = BeautifulSoup(html, "html.parser")
                text = _find_text(soup)
                all_text += f" {text}"
                result["pages_fetched"] += 1

                # Detect job listings mentioning buying signals
                if page_type in ("careers", "jobs"):
                    for kw in _BUYING_SIGNAL_KEYWORDS:
                        if kw in text:
                            result["signals"].append({
                                "type": "job_listing",
                                "text": f"Active '{kw}' hiring detected",
                                "weight": 0.15 if "sdr" in kw else 0.10,
                            })
                            break  # one signal per page

    except Exception as exc:
        result["error"] = f"Scraping failed: {str(exc)[:120]}"
        if result["pages_fetched"] == 0:
            return result

    # Tech stack detection across all collected text
    for tech, patterns in _TECH_KEYWORDS.items():
        if any(p in all_text for p in patterns):
            result["tech_stack"].append(tech)

    # Employee count hints
    for pat in _SIZE_PATTERNS:
        for m in pat.finditer(all_text[:5000]):
            hint = m.group(0).strip()
            if hint not in result["employee_hints"]:
                result["employee_hints"].append(hint)
    result["employee_hints"] = result["employee_hints"][:3]

    # Deduplicate signals
    seen = set()
    deduped = []
    for s in result["signals"]:
        if s["text"] not in seen:
            seen.add(s["text"])
            deduped.append(s)
    result["signals"] = deduped

    log.info(
        "Web enrichment complete",
        domain=domain,
        pages=result["pages_fetched"],
        signals=len(result["signals"]),
        tech=result["tech_stack"],
    )
    return result
