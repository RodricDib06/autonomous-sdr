"""
CRM Sync Service

Pushes qualified leads to a CRM so the sales team has full context.

PoC: logs what would be synced. The export_service already generates
     CSV-formatted rows that can be manually imported into any CRM.
     The live-push functions below are structured to work in production
     with minimal changes (swap the mock body for real HTTP calls).

# PRODUCTION CRM integrations:
#
# ── HubSpot (free CRM tier available) ─────────────────────────────────────
#   pip install hubspot-api-client
#   from hubspot import HubSpot
#   client = HubSpot(access_token=settings.HUBSPOT_API_KEY)
#   # Create or update contact:
#   from hubspot.crm.contacts.models import SimplePublicObjectInput
#   props = SimplePublicObjectInput(properties={
#       "email": lead.email, "firstname": first, "lastname": last,
#       "company": lead.company, "jobtitle": enrichment.job_title,
#       "hs_lead_status": verdict.final_verdict,
#   })
#   client.crm.contacts.basic_api.create(simple_public_object_input=props)
#   Docs: https://developers.hubspot.com/docs/api/crm/contacts
#
# ── Salesforce (developer org is free) ────────────────────────────────────
#   pip install simple-salesforce
#   from simple_salesforce import Salesforce
#   sf = Salesforce(username=..., password=..., security_token=...,
#                   domain="login")
#   sf.Lead.create({
#       "FirstName": first, "LastName": last, "Email": lead.email,
#       "Company": lead.company, "Title": enrichment.job_title,
#       "LeadSource": lead.source, "Status": verdict.final_verdict,
#       "Description": verdict.analysis_reasoning,
#   })
#   Docs: https://developer.salesforce.com/docs/atlas.en-us.api.meta/api/sforce_api_objects_lead.htm
#
# ── Pipedrive (free trial / developer sandbox) ────────────────────────────
#   import requests
#   # Create person:
#   resp = requests.post(
#       "https://api.pipedrive.com/v1/persons",
#       params={"api_token": settings.PIPEDRIVE_API_KEY},
#       json={"name": lead.name, "email": [{"value": lead.email}],
#             "org_id": org_id},  # org_id from a prior POST /organizations call
#   )
#   person_id = resp.json()["data"]["id"]
#   # Create deal:
#   requests.post(
#       "https://api.pipedrive.com/v1/deals",
#       params={"api_token": settings.PIPEDRIVE_API_KEY},
#       json={"title": f"{lead.company} - {verdict.final_verdict}",
#             "person_id": person_id, "status": "open"},
#   )
#   Docs: https://developers.pipedrive.com/docs/api/v1
"""

import logging
from sqlalchemy.orm import Session

from app.database.models import Lead, Enrichment, Verdict
from app.config import settings
from app.utils.time import utcnow

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def sync_lead_to_crm(db: Session, lead_id: str) -> dict:
    """
    Push a qualified lead to the configured CRM.

    Returns {"crm": str, "status": str, "external_id": str | None}
    """
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        return {"crm": "none", "status": "lead_not_found"}

    enrichment = db.query(Enrichment).filter(Enrichment.lead_id == lead_id).first()
    verdict = db.query(Verdict).filter(Verdict.lead_id == lead_id).first()

    # Normalise name
    parts = (lead.name or "").split(" ", 1)
    first = parts[0]
    last = parts[1] if len(parts) > 1 else ""

    payload = _build_payload(lead, enrichment, verdict, first, last)

    if settings.HUBSPOT_API_KEY:
        return _sync_hubspot(payload)
    elif settings.SALESFORCE_USERNAME:
        return _sync_salesforce(payload)
    elif settings.PIPEDRIVE_API_KEY:
        return _sync_pipedrive(payload)
    else:
        return _sync_mock(payload)


# ---------------------------------------------------------------------------
# Payload builder (shared across CRMs)
# ---------------------------------------------------------------------------

def _build_payload(lead: Lead, enrichment, verdict, first: str, last: str) -> dict:
    return {
        "first_name": first,
        "last_name": last,
        "email": lead.email,
        "company": lead.company,
        "source": lead.source,
        "job_title": enrichment.job_title if enrichment else None,
        "seniority": enrichment.seniority if enrichment else None,
        "company_size": enrichment.company_size if enrichment else None,
        "industry": enrichment.industry if enrichment else None,
        "verdict": verdict.final_verdict if verdict else None,
        "confidence": verdict.confidence_score if verdict else None,
        "reasoning": verdict.analysis_reasoning if verdict else None,
        "bant_scores": verdict.bant_scores if verdict else None,
        "synced_at": utcnow().isoformat(),
        "lead_id": lead.id,
    }


# ---------------------------------------------------------------------------
# CRM adapters
# ---------------------------------------------------------------------------

def _sync_hubspot(payload: dict) -> dict:
    """
    # PRODUCTION:
    #   from hubspot import HubSpot
    #   from hubspot.crm.contacts.models import SimplePublicObjectInput
    #   client = HubSpot(access_token=settings.HUBSPOT_API_KEY)
    #   props = SimplePublicObjectInput(properties={
    #       "email": payload["email"],
    #       "firstname": payload["first_name"],
    #       "lastname": payload["last_name"],
    #       "company": payload["company"],
    #       "jobtitle": payload["job_title"] or "",
    #       "hs_lead_status": payload["verdict"] or "NEW",
    #       "sdr_verdict": payload["verdict"],
    #       "sdr_confidence": str(payload["confidence"] or ""),
    #       "sdr_reasoning": payload["reasoning"] or "",
    #   })
    #   try:
    #       contact = client.crm.contacts.basic_api.create(simple_public_object_input=props)
    #       return {"crm": "hubspot", "status": "created", "external_id": contact.id}
    #   except ApiException as e:
    #       if e.status == 409:  # already exists
    #           # PATCH the existing contact instead
    #           ...
    #       raise
    """
    log.info(f"[crm/hubspot] MOCK sync → {payload['email']} ({payload['verdict']})")
    return {"crm": "hubspot", "status": "mock_sync", "external_id": None}


def _sync_salesforce(payload: dict) -> dict:
    """
    # PRODUCTION:
    #   from simple_salesforce import Salesforce, SalesforceResourceNotFound
    #   sf = Salesforce(
    #       username=settings.SALESFORCE_USERNAME,
    #       password=settings.SALESFORCE_PASSWORD,
    #       security_token=settings.SALESFORCE_SECURITY_TOKEN,
    #   )
    #   result = sf.Lead.create({
    #       "FirstName": payload["first_name"],
    #       "LastName": payload["last_name"] or payload["company"],
    #       "Email": payload["email"],
    #       "Company": payload["company"],
    #       "Title": payload["job_title"] or "",
    #       "LeadSource": payload["source"],
    #       "Status": payload["verdict"] or "Open",
    #       "Description": payload["reasoning"] or "",
    #       "Industry": payload["industry"] or "",
    #   })
    #   return {"crm": "salesforce", "status": "created", "external_id": result["id"]}
    """
    log.info(f"[crm/salesforce] MOCK sync → {payload['email']} ({payload['verdict']})")
    return {"crm": "salesforce", "status": "mock_sync", "external_id": None}


def _sync_pipedrive(payload: dict) -> dict:
    """
    # PRODUCTION:
    #   import requests
    #   base = "https://api.pipedrive.com/v1"
    #   token = settings.PIPEDRIVE_API_KEY
    #   # Create/find org
    #   org_resp = requests.post(f"{base}/organizations",
    #       params={"api_token": token},
    #       json={"name": payload["company"]})
    #   org_id = org_resp.json()["data"]["id"]
    #   # Create person
    #   person_resp = requests.post(f"{base}/persons",
    #       params={"api_token": token},
    #       json={"name": f"{payload['first_name']} {payload['last_name']}",
    #             "email": [{"value": payload["email"]}], "org_id": org_id})
    #   person_id = person_resp.json()["data"]["id"]
    #   # Create deal
    #   deal_resp = requests.post(f"{base}/deals",
    #       params={"api_token": token},
    #       json={"title": f"{payload['company']} — {payload['verdict']}",
    #             "person_id": person_id, "status": "open"})
    #   return {"crm": "pipedrive", "status": "created",
    #           "external_id": str(deal_resp.json()["data"]["id"])}
    """
    log.info(f"[crm/pipedrive] MOCK sync → {payload['email']} ({payload['verdict']})")
    return {"crm": "pipedrive", "status": "mock_sync", "external_id": None}


def _sync_mock(payload: dict) -> dict:
    """No CRM configured — log only. Acts as a dry-run."""
    log.info(
        f"[crm/mock] Would sync: {payload['email']} | verdict={payload['verdict']} "
        f"| company={payload['company']} | confidence={payload['confidence']}"
    )
    return {"crm": "mock", "status": "logged", "external_id": None}
