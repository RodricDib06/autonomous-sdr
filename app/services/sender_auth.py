"""
Sending-domain authentication check — SPF, DKIM, DMARC.

Gmail and Yahoo reject or spam-folder mail from domains that don't
authenticate: every sender needs SPF or DKIM, and bulk senders need both
plus DMARC. A mailbox on an unauthenticated domain burns its reputation on
the first batch, so the rotation pool skips it until DNS is fixed.

DKIM can't be checked exhaustively — the selector is chosen by the mail
provider and not discoverable — so we probe the common ones. "Not found
among common selectors" is reported as unknown, never as a failure.
"""

from __future__ import annotations

from app.config import settings
from app.utils.time import utcnow

DNS_TIMEOUT_SECONDS = 3.0

# Google Workspace, Microsoft 365, Zoho, Mailchimp/Mandrill, Fastmail,
# Proton, SendGrid/Mailgun-style and generic defaults
COMMON_DKIM_SELECTORS = (
    "google", "selector1", "selector2", "zoho", "k1", "k2", "mandrill",
    "fm1", "fm2", "protonmail", "s1", "s2", "smtp", "mail", "dkim", "default",
)

RECHECK_AFTER_HOURS = 24


def _txt(name: str, resolver) -> list[str] | None:
    """TXT strings at `name`; [] when there are none, None when DNS failed."""
    import dns.resolver

    try:
        answers = resolver.resolve(name, "TXT")
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    except Exception:
        return None
    return [b"".join(r.strings).decode(errors="replace") for r in answers]


def _make_resolver():
    import dns.resolver

    resolver = dns.resolver.Resolver()
    resolver.timeout = DNS_TIMEOUT_SECONDS
    resolver.lifetime = DNS_TIMEOUT_SECONDS
    return resolver


def check_domain(domain: str, resolver=None) -> dict:
    """
    {"domain", "spf", "dkim", "dmarc", "can_send", "issues", "checked_at"}.
    Each of spf/dkim/dmarc is {"ok": True | False | None, ...}; None means
    the lookup failed or (for DKIM) the selector is unknown.
    """
    resolver = resolver or _make_resolver()
    domain = domain.strip().lower().rstrip(".")
    issues: list[str] = []

    spf_records = _txt(domain, resolver)
    if spf_records is None:
        spf = {"ok": None, "record": None}
    else:
        record = next((r for r in spf_records if r.lower().startswith("v=spf1")), None)
        spf = {"ok": record is not None, "record": record}
        if record is None:
            issues.append(f"No SPF record: add a TXT record on {domain} starting with v=spf1")

    dmarc_records = _txt(f"_dmarc.{domain}", resolver)
    if dmarc_records is None:
        dmarc = {"ok": None, "record": None, "policy": None}
    else:
        record = next((r for r in dmarc_records if r.upper().startswith("V=DMARC1")), None)
        policy = None
        if record:
            for part in record.split(";"):
                key, _, value = part.strip().partition("=")
                if key.lower() == "p":
                    policy = value.strip().lower()
        dmarc = {"ok": record is not None, "record": record, "policy": policy}
        if record is None:
            issues.append(f"No DMARC record: add a TXT record on _dmarc.{domain} (e.g. v=DMARC1; p=none)")

    dkim = {"ok": None, "selector": None}
    for selector in COMMON_DKIM_SELECTORS:
        records = _txt(f"{selector}._domainkey.{domain}", resolver)
        if records and any("p=" in r for r in records):
            dkim = {"ok": True, "selector": selector}
            break

    # Gmail's floor for every sender: SPF or DKIM. Only a *confirmed* missing
    # SPF with no DKIM found blocks — a DNS outage never does.
    can_send = not (spf["ok"] is False and dkim["ok"] is not True)
    if not can_send:
        issues.insert(0, "Domain has no SPF and no DKIM we could find — Gmail and Yahoo will reject this mail")

    return {
        "domain": domain,
        "spf": spf,
        "dkim": dkim,
        "dmarc": dmarc,
        "can_send": can_send,
        "issues": issues,
        "checked_at": utcnow().isoformat(),
    }


def check_mailbox(db, mailbox, resolver=None) -> dict:
    """Run the check for a mailbox's domain and store the result on it."""
    result = check_domain(mailbox.email.rsplit("@", 1)[-1], resolver=resolver)
    mailbox.dns_auth = result
    mailbox.dns_checked_at = utcnow()
    db.commit()
    return result


def mailbox_may_send(db, mailbox) -> bool:
    """
    Rotation gate. Checks lazily (and re-checks daily) so mailboxes created
    before this existed are covered too. Disabled with SENDER_AUTH_CHECK_ENABLED.
    """
    if not settings.SENDER_AUTH_CHECK_ENABLED:
        return True
    stale = (
        mailbox.dns_checked_at is None
        or (utcnow() - mailbox.dns_checked_at).total_seconds() > RECHECK_AFTER_HOURS * 3600
    )
    if stale or not mailbox.dns_auth:
        check_mailbox(db, mailbox)
    return bool((mailbox.dns_auth or {}).get("can_send", True))
