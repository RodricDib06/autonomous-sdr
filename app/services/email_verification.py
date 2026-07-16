"""
Email verification — the pre-send deliverability gate.

Bounces are what actually burn a sending domain: a few percent hard-bounce
rate and Gmail/Outlook start junking everything from that domain. So no
address gets an outreach email until it passes:

  1. syntax        — RFC-compliant address (email-validator)
  2. disposable    — throwaway domains (mailinator, yopmail, …) are undeliverable
  3. role account  — info@/sales@/noreply@ are "risky": deliverable but rarely
                     a person, and spam-trap-prone
  4. MX lookup     — the domain must publish MX (or, per RFC 5321, an A/AAAA
                     fallback) records; NXDOMAIN/no records → undeliverable
  5. SMTP probe    — optional RCPT TO check against the primary MX (off by
                     default: most hosts block outbound port 25)

Statuses: valid | risky | undeliverable | unknown. Only "undeliverable"
blocks sending — an unknown (e.g. DNS timeout) must never halt the pipeline.
Results are cached per domain (DNS) and stored on the lead with a TTL.
"""

from __future__ import annotations

import logging
import re
import smtplib
import threading
import time
from dataclasses import dataclass, field
from datetime import timedelta

from app.config import settings
from app.utils.time import utcnow

log = logging.getLogger(__name__)

DNS_TIMEOUT_SECONDS = 5.0
SMTP_PROBE_TIMEOUT_SECONDS = 10.0
_MX_CACHE_TTL_SECONDS = 3600.0

# Well-known throwaway providers. Deliberately a short, high-precision list —
# a stale mega-list misclassifies real domains, which is worse.
DISPOSABLE_DOMAINS = frozenset({
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "yopmail.com",
    "tempmail.com", "temp-mail.org", "trashmail.com", "throwawaymail.com",
    "getnada.com", "maildrop.cc", "sharklasers.com", "dispostable.com",
    "fakeinbox.com", "mintemail.com", "mailnesia.com", "spamgourmet.com",
})

ROLE_ACCOUNTS = frozenset({
    "admin", "administrator", "info", "support", "sales", "contact", "help",
    "office", "mail", "team", "hello", "hr", "jobs", "careers", "billing",
    "noreply", "no-reply", "donotreply", "postmaster", "abuse", "webmaster",
    "marketing", "press", "security", "root",
})

_LOCAL_PART_RE = re.compile(r"^([^@]+)@")


@dataclass
class VerificationResult:
    email: str
    status: str                       # valid | risky | undeliverable | unknown
    reason: str
    checks: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"email": self.email, "status": self.status, "reason": self.reason,
                "checks": self.checks, "verified_at": utcnow().isoformat()}


# ---------------------------------------------------------------------------
# MX lookup with a small in-process cache
# ---------------------------------------------------------------------------

_mx_cache: dict[str, tuple[float, tuple[bool | None, str, list[str]]]] = {}
_mx_lock = threading.Lock()


def _resolve_mx(domain: str) -> tuple[bool | None, str, list[str]]:
    """
    (has_mail_host, detail, mx_hosts). has_mail_host is None on DNS
    failure/timeout — "we couldn't check" is not "undeliverable".
    """
    import dns.resolver

    resolver = dns.resolver.Resolver()
    resolver.timeout = DNS_TIMEOUT_SECONDS
    resolver.lifetime = DNS_TIMEOUT_SECONDS

    try:
        answers = resolver.resolve(domain, "MX")
        hosts = sorted(
            (r.preference, str(r.exchange).rstrip(".")) for r in answers
        )
        # A "null MX" (RFC 7505: single record pointing at the root) is an
        # explicit "this domain never accepts mail"
        if len(hosts) == 1 and hosts[0][1] in ("", "."):
            return False, "Domain publishes a null MX (does not accept mail)", []
        return True, f"{len(hosts)} MX record(s)", [h for _, h in hosts]
    except dns.resolver.NXDOMAIN:
        return False, "Domain does not exist (NXDOMAIN)", []
    except dns.resolver.NoAnswer:
        # RFC 5321 §5.1: fall back to an A/AAAA record
        for rrtype in ("A", "AAAA"):
            try:
                resolver.resolve(domain, rrtype)
                return True, f"No MX, but {rrtype} record present (RFC 5321 fallback)", [domain]
            except Exception:
                continue
        return False, "No MX, A, or AAAA records", []
    except Exception as e:
        return None, f"DNS lookup failed: {e}", []


def _resolve_mx_cached(domain: str) -> tuple[bool | None, str, list[str]]:
    now = time.monotonic()
    with _mx_lock:
        hit = _mx_cache.get(domain)
        if hit and now - hit[0] < _MX_CACHE_TTL_SECONDS:
            return hit[1]

    result = _resolve_mx(domain)
    if result[0] is not None:  # don't cache transient DNS failures
        with _mx_lock:
            _mx_cache[domain] = (now, result)
    return result


# ---------------------------------------------------------------------------
# Optional SMTP RCPT probe
# ---------------------------------------------------------------------------

def _smtp_probe(email: str, mx_host: str) -> tuple[bool | None, str]:
    """
    Ask the recipient's own MX whether the mailbox exists (RCPT TO, then
    quit without sending DATA). None = inconclusive (greylisting, catch-all,
    blocked port); only a definitive 5xx counts as a rejection.
    """
    try:
        with smtplib.SMTP(mx_host, 25, timeout=SMTP_PROBE_TIMEOUT_SECONDS) as server:
            server.helo()
            server.mail("")
            code, message = server.rcpt(email)
        if 200 <= code < 300:
            return True, f"RCPT accepted ({code})"
        if 500 <= code < 600:
            return False, f"RCPT rejected ({code}: {message.decode(errors='replace')[:120]})"
        return None, f"Inconclusive RCPT response ({code})"
    except Exception as e:
        return None, f"SMTP probe failed: {e}"


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_email(email: str, smtp_probe: bool | None = None) -> VerificationResult:
    """Run the full check chain. Never raises."""
    checks: dict = {}
    email = (email or "").strip().lower()

    # 1. Syntax
    try:
        from email_validator import validate_email
        validate_email(email, check_deliverability=False)
        checks["syntax"] = {"ok": True}
    except Exception as e:
        checks["syntax"] = {"ok": False, "detail": str(e)[:200]}
        return VerificationResult(email, "undeliverable", "Invalid address syntax", checks)

    local_part = _LOCAL_PART_RE.match(email).group(1)
    domain = email.split("@", 1)[1]

    # 2. Disposable domain
    disposable = domain in DISPOSABLE_DOMAINS
    checks["disposable"] = {"ok": not disposable}
    if disposable:
        return VerificationResult(email, "undeliverable", f"Disposable email domain ({domain})", checks)

    # 3. Role account (deliverable, but rarely a buying human)
    is_role = local_part in ROLE_ACCOUNTS
    checks["role_account"] = {"ok": not is_role}

    # 4. MX
    has_mx, mx_detail, mx_hosts = _resolve_mx_cached(domain)
    checks["mx"] = {"ok": has_mx, "detail": mx_detail}
    if has_mx is False:
        return VerificationResult(email, "undeliverable", mx_detail, checks)
    if has_mx is None:
        return VerificationResult(email, "unknown", mx_detail, checks)

    # 5. Optional SMTP probe
    probe_enabled = settings.EMAIL_VERIFICATION_SMTP_PROBE if smtp_probe is None else smtp_probe
    if probe_enabled:
        exists, probe_detail = _smtp_probe(email, mx_hosts[0]) if mx_hosts else (None, "No MX host")
        checks["smtp_probe"] = {"ok": exists, "detail": probe_detail}
        if exists is False:
            return VerificationResult(email, "undeliverable", probe_detail, checks)

    if is_role:
        return VerificationResult(email, "risky", f"Role account ({local_part}@)", checks)
    return VerificationResult(email, "valid", "All checks passed", checks)


# ---------------------------------------------------------------------------
# Lead integration
# ---------------------------------------------------------------------------

def verify_lead_email(db, lead, force: bool = False) -> str:
    """
    Verify a lead's address and persist the result on the lead. Reuses a
    stored verdict inside the TTL; returns the status string. With
    verification disabled, everything passes as "unknown".
    """
    if not settings.EMAIL_VERIFICATION_ENABLED:
        return lead.email_verification_status or "unknown"

    ttl_days = settings.EMAIL_VERIFICATION_TTL_DAYS
    if (
        not force
        and lead.email_verification_status
        and lead.email_verified_at
        and (ttl_days == 0 or utcnow() - lead.email_verified_at < timedelta(days=ttl_days))
    ):
        return lead.email_verification_status

    result = verify_email(lead.email)
    lead.email_verification_status = result.status
    lead.email_verified_at = utcnow()
    lead.email_verification_detail = result.to_dict()
    db.commit()

    if result.status == "undeliverable":
        log.info(f"[verify] {lead.email} undeliverable — {result.reason}")
    return result.status


def mark_undeliverable(db, lead, reason: str) -> None:
    """Hard-bounce path: overwrite whatever the checks said — the MX has spoken."""
    lead.email_verification_status = "undeliverable"
    lead.email_verified_at = utcnow()
    lead.email_verification_detail = {
        "email": lead.email, "status": "undeliverable", "reason": reason,
        "checks": {"bounce": {"ok": False, "detail": reason[:300]}},
        "verified_at": utcnow().isoformat(),
    }
    db.commit()
