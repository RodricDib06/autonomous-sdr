"""
Tenancy helpers — organization resolution and query scoping.

Scoping contract:
  - Callers pass the requesting user's `org_id` into queries.
  - `org_id is None` (legacy JWTs / pre-migration rows) means "no scoping",
    which preserves single-tenant behaviour.
  - Rows created going forward always carry an org_id.

Unauthenticated ingest (public webhooks) lands in the default organization;
authenticated ingest (API key / JWT) lands in the caller's organization.
"""

import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Lead, Organization
from app.utils.time import utcnow

log = logging.getLogger(__name__)

DEFAULT_ORG_SLUG = "default"


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug[:100] or "org"


def get_default_org(db: Session) -> Organization:
    """Return the default organization, creating it on first use."""
    org = db.query(Organization).filter(Organization.slug == DEFAULT_ORG_SLUG).first()
    if org is None:
        org = Organization(name="Default Organization", slug=DEFAULT_ORG_SLUG, created_at=utcnow())
        db.add(org)
        db.commit()
        db.refresh(org)
        log.info("[tenancy] Created default organization %s", org.id[:8])
    return org


def create_org(db: Session, name: str) -> Organization:
    base = slugify(name)
    slug = base
    n = 2
    while db.query(Organization).filter(Organization.slug == slug).first() is not None:
        slug = f"{base}-{n}"
        n += 1
    org = Organization(name=name, slug=slug, created_at=utcnow())
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def scoped(query, model, org_id: str | None):
    """Apply org filtering to a query when the caller belongs to an org."""
    if org_id is None:
        return query
    return query.filter(model.org_id == org_id)


def org_lead_ids(org_id: str):
    """SELECT of the org's lead ids, for `col.in_(...)` on tables keyed by lead."""
    return select(Lead.id).where(Lead.org_id == org_id)


def scoped_by_lead(query, lead_id_col, org_id: str | None):
    """
    Org-scope a table that has no org_id of its own but hangs off a lead
    (verdicts, outreach emails, conversations, LLM calls, ...). A subquery
    rather than a join, so it composes with queries that already join Lead.
    """
    if org_id is None:
        return query
    return query.filter(lead_id_col.in_(org_lead_ids(org_id)))


def is_operator(user) -> bool:
    """Member of the org that runs the install (or a pre-tenancy user)."""
    if user.org_id is None:
        return True
    return user.organization is not None and user.organization.slug == DEFAULT_ORG_SLUG


def is_instance_admin(user) -> bool:
    """
    Instance-wide settings (AI/enrichment provider, Slack webhook, the shared
    BANT weights) affect every tenant, so only admins of the default org — the
    operator who runs the install — may change them. Legacy users with no org
    predate tenancy and are the operator by definition.
    """
    return user.role == "admin" and is_operator(user)


def get_org_setting(db: Session, org_id: str | None, key: str, default=None):
    """Read a per-org setting with fallback to the default org, then `default`."""
    org = None
    if org_id:
        org = db.query(Organization).filter(Organization.id == org_id).first()
    if org is None:
        org = db.query(Organization).filter(Organization.slug == DEFAULT_ORG_SLUG).first()
    if org and org.settings and key in org.settings:
        return org.settings[key]
    return default


def set_org_setting(db: Session, org_id: str | None, key: str, value) -> dict:
    """Write a per-org setting (default org when caller has none)."""
    org = None
    if org_id:
        org = db.query(Organization).filter(Organization.id == org_id).first()
    if org is None:
        org = get_default_org(db)
    settings_dict = dict(org.settings or {})
    settings_dict[key] = value
    org.settings = settings_dict
    db.commit()
    return settings_dict
