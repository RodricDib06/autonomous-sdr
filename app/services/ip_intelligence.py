"""
IP Intelligence — Reverse-IP Visitor De-anonymization

Identifies the company behind a web visitor's IP address using the free
ip-api.com service (no API key required, 45 req/min limit).

Why this matters: B2B companies browsing your site from a corporate office
network show their company's autonomous system (AS) in the IP's WHOIS/BGP
data. If a Stripe engineer visits your pricing page, their IP will map to
"Stripe" — not their ISP. This de-anonymizes ~20–40% of tech company visitors.

Limitations:
  - Works best for companies with dedicated office networks or their own ASN
  - Remote/WFH employees show their ISP (Comcast, etc.) — we filter these out
  - Cloud-hosted traffic (crawlers, bots) shows AWS/GCP/Cloudflare — filtered

Free tier: ip-api.com allows 45 requests/min without auth.
  Production alternative: Clearbit Reveal ($99/mo), Leadfeeder, or Albacross.

# PRODUCTION Clearbit Reveal (drop-in replacement):
#   GET https://reveal.clearbit.com/v1/companies/find?domain={domain}
#   Headers: Authorization: Bearer {CLEARBIT_API_KEY}
#   Returns: {domain, company: {name, category, ...}}
#   Use visitor IP → resolve to domain → query Clearbit for company profile.
"""

from __future__ import annotations

import logging
import re
import requests

log = logging.getLogger(__name__)

_IP_API_URL = "http://ip-api.com/json/{ip}"
_IP_API_FIELDS = "status,org,company,isp,city,country,countryCode,query"
_TIMEOUT = 4.0

# ---------------------------------------------------------------------------
# Filter patterns — orgs matching these are not useful leads
# ---------------------------------------------------------------------------

_ISP_PATTERNS = re.compile(
    r"\b(comcast|at&t|verizon|charter|spectrum|cox|centurylink|frontier|"
    r"t-mobile|sprint|boost|cricket|metro|xfinity|bell|shaw|rogers|telus|"
    r"vodafone|bt group|virgin media|sky broadband|deutsch telekom|orange|"
    r"residential|broadband|cable|dsl|fiber|internet service)\b",
    re.I,
)

_CLOUD_CDN_PATTERNS = re.compile(
    r"\b(amazon web services|amazon\.com|google llc|google cloud|microsoft "
    r"corporation|azure|cloudflare|digitalocean|linode|vultr|hetzner|ovh|"
    r"fastly|akamai|stackpath|incapsula|sucuri|zscaler|paloalto)\b",
    re.I,
)

_VPN_PATTERNS = re.compile(
    r"\b(nordvpn|expressvpn|private internet access|pia|protonvpn|mullvad|"
    r"surfshark|ipvanish|hotspot shield|tunnelbear|windscribe|vpn|proxy|"
    r"anonymizer|tor exit)\b",
    re.I,
)

_AS_PREFIX = re.compile(r"^AS\d+\s+", re.I)


def _clean_org(raw: str) -> str:
    """Strip 'AS12345 ' prefix from org strings returned by ip-api."""
    return _AS_PREFIX.sub("", raw).strip()


def _is_useful_org(org: str) -> bool:
    """Return False for ISPs, cloud providers, VPNs, and other noise."""
    if not org or len(org) < 3:
        return False
    if _ISP_PATTERNS.search(org):
        return False
    if _CLOUD_CDN_PATTERNS.search(org):
        return False
    if _VPN_PATTERNS.search(org):
        return False
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def identify_visitor(ip: str) -> dict:
    """
    Attempt to identify the company behind a visitor IP.

    Returns:
      {
        identified: bool,
        company: str | None,       # cleaned org name
        org_raw: str | None,       # raw ASN org string
        city: str | None,
        country: str | None,
        country_code: str | None,
        domain: str | None,        # guessed email domain from company name
        source: "ip_api" | "unavailable",
      }
    """
    _empty = {
        "identified": False,
        "company": None,
        "org_raw": None,
        "city": None,
        "country": None,
        "country_code": None,
        "domain": None,
        "source": "unavailable",
    }

    if not ip or ip in ("127.0.0.1", "::1", "localhost"):
        return _empty

    try:
        resp = requests.get(
            _IP_API_URL.format(ip=ip),
            params={"fields": _IP_API_FIELDS},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.debug(f"[ip_intelligence] ip-api request failed for {ip}: {e}")
        return _empty

    if data.get("status") != "success":
        return _empty

    raw_org = data.get("org", "") or data.get("company", "") or ""
    cleaned = _clean_org(raw_org)

    if not _is_useful_org(cleaned):
        log.debug(f"[ip_intelligence] {ip} → org '{cleaned}' filtered out")
        return _empty

    # Guess email domain: lowercase company, strip spaces/punctuation
    domain_guess = re.sub(r"[^a-z0-9]", "", cleaned.lower()) + ".com"

    log.info(f"[ip_intelligence] {ip} → company='{cleaned}' ({data.get('city')}, {data.get('countryCode')})")
    return {
        "identified": True,
        "company": cleaned,
        "org_raw": raw_org,
        "city": data.get("city"),
        "country": data.get("country"),
        "country_code": data.get("countryCode"),
        "domain": domain_guess,
        "source": "ip_api",
    }


def is_private_ip(ip: str) -> bool:
    """Return True for RFC-1918 and loopback addresses — skip these entirely."""
    import ipaddress
    try:
        addr = ipaddress.ip_address(ip)
        return addr.is_private or addr.is_loopback or addr.is_link_local
    except ValueError:
        return False
