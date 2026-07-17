"""
Bidirectional HubSpot sync.

Outbound (existing push, now real): qualified leads are upserted as HubSpot
contacts with verdict/confidence/reasoning as properties; the contact id is
stored on the lead so inbound events resolve without lookups.

Inbound (the actual point): webhook subscriptions on lifecycle/deal changes
flow real outcomes back into `conversion_status` — which is what trains the
ML scorer, drives the BANT optimization loop, and makes backtests reflect
reality instead of whatever the CSV said last quarter.

Conflict policy: the CRM wins on ownership and stage (`conversion_status`);
the platform wins on everything it computes (verdicts, scores, decay) —
inbound events never touch those.

Auth: per-org OAuth connection (tokens encrypted at rest, auto-refresh —
HubSpot access tokens live ~30 minutes). The legacy HUBSPOT_API_KEY private
app token still works for outbound-only setups.

Webhook authenticity: X-HubSpot-Signature-v3 — HMAC-SHA256 over
method+uri+body+timestamp with the app's client secret, rejected when the
timestamp is stale.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta

import requests
from jose import jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import CrmConnection, CrmSyncLog, Lead, LeadHistory
from app.utils.time import utcnow

log = logging.getLogger(__name__)

HTTP_TIMEOUT_SECONDS = 20
STATE_TTL_MINUTES = 10
SIGNATURE_MAX_AGE_SECONDS = 300
_TOKEN_REFRESH_LEEWAY_SECONDS = 120

AUTHORIZE_URL = "https://app.hubspot.com/oauth/authorize"
TOKEN_URL = "https://api.hubapi.com/oauth/v1/token"
API_BASE = "https://api.hubapi.com"

SCOPES = [
    "crm.objects.contacts.read",
    "crm.objects.contacts.write",
    "crm.objects.deals.read",
]

# CRM stage vocabulary → our conversion_status. Deliberately conservative:
# stages we can't map cleanly are ignored rather than guessed.
LIFECYCLE_TO_CONVERSION = {
    "salesqualifiedlead": "qualified",
    "opportunity": "qualified",
    "customer": "won",
    "evangelist": "won",
}
DEALSTAGE_TO_CONVERSION = {
    "closedwon": "won",
    "closedlost": "lost",
}


def hubspot_oauth_configured() -> bool:
    return bool(settings.HUBSPOT_CLIENT_ID and settings.HUBSPOT_CLIENT_SECRET)


def get_connection(db: Session, org_id: str | None) -> CrmConnection | None:
    q = db.query(CrmConnection).filter(
        CrmConnection.provider == "hubspot", CrmConnection.is_active.is_(True)
    )
    if org_id is not None:
        q = q.filter(CrmConnection.org_id == org_id)
    return q.first()


def log_sync(
    db: Session,
    *,
    org_id: str | None,
    direction: str,
    event_type: str,
    lead_id: str | None = None,
    external_id: str | None = None,
    payload: dict | None = None,
    success: bool = True,
    error: str | None = None,
) -> None:
    db.add(CrmSyncLog(
        org_id=org_id, provider="hubspot", direction=direction,
        lead_id=lead_id, external_id=external_id, event_type=event_type,
        payload=payload, success=success, error_message=(error or None) and str(error)[:500],
    ))
    db.commit()


# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------

def create_state(user_id: str, org_id: str | None, redirect_uri: str) -> str:
    return jwt.encode(
        {"sub": user_id, "org": org_id, "redirect_uri": redirect_uri,
         "purpose": "crm_oauth", "exp": utcnow() + timedelta(minutes=STATE_TTL_MINUTES)},
        settings.SECRET_KEY, algorithm=settings.ALGORITHM,
    )


def decode_state(state: str) -> dict:
    from jose import JWTError
    try:
        payload = jwt.decode(state, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as e:
        raise ValueError(f"Invalid OAuth state: {e}")
    if payload.get("purpose") != "crm_oauth":
        raise ValueError("OAuth state does not match this flow")
    return payload


def build_authorize_url(state: str, redirect_uri: str) -> str:
    from urllib.parse import urlencode
    return AUTHORIZE_URL + "?" + urlencode({
        "client_id": settings.HUBSPOT_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": " ".join(SCOPES),
        "state": state,
    })


def _token_request(data: dict) -> dict:
    resp = requests.post(
        TOKEN_URL,
        data={"client_id": settings.HUBSPOT_CLIENT_ID,
              "client_secret": settings.HUBSPOT_CLIENT_SECRET, **data},
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    if not resp.ok:
        raise RuntimeError(f"HubSpot token endpoint returned {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def _token_blob(tokens: dict, refresh_token: str) -> dict:
    return {
        "access_token": tokens["access_token"],
        "refresh_token": refresh_token,
        "expires_at": (utcnow() + timedelta(seconds=int(tokens.get("expires_in", 1800)))).isoformat(),
    }


def exchange_code(code: str, redirect_uri: str) -> dict:
    tokens = _token_request({
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
    })
    return _token_blob(tokens, refresh_token=tokens["refresh_token"])


def fetch_portal_id(access_token: str) -> str:
    resp = requests.get(
        f"{API_BASE}/oauth/v1/access-tokens/{access_token}",
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return str(resp.json().get("hub_id", ""))


def get_access_token(db: Session, connection: CrmConnection) -> str:
    from app.services.mailbox_service import decrypt_secret, encrypt_secret

    blob = json.loads(decrypt_secret(connection.token_encrypted))
    expires_at = datetime.fromisoformat(blob["expires_at"])
    if utcnow() + timedelta(seconds=_TOKEN_REFRESH_LEEWAY_SECONDS) < expires_at:
        return blob["access_token"]

    tokens = _token_request({
        "grant_type": "refresh_token", "refresh_token": blob["refresh_token"],
    })
    blob = _token_blob(tokens, refresh_token=tokens.get("refresh_token") or blob["refresh_token"])
    connection.token_encrypted = encrypt_secret(json.dumps(blob))
    db.commit()
    return blob["access_token"]


# ---------------------------------------------------------------------------
# Webhook signature (v3)
# ---------------------------------------------------------------------------

def validate_signature_v3(
    method: str, uri: str, body: bytes, timestamp: str, signature: str,
    now: datetime | None = None,
) -> bool:
    """HMAC-SHA256(client_secret, method+uri+body+timestamp), base64. Stale
    timestamps rejected — replayed webhooks must not mutate leads."""
    if not settings.HUBSPOT_CLIENT_SECRET or not timestamp or not signature:
        return False
    try:
        ts_ms = int(timestamp)
    except ValueError:
        return False
    now = now or utcnow()
    if abs(now.timestamp() * 1000 - ts_ms) > SIGNATURE_MAX_AGE_SECONDS * 1000:
        return False

    message = method.upper() + uri + body.decode("utf-8") + timestamp
    expected = base64.b64encode(
        hmac.new(settings.HUBSPOT_CLIENT_SECRET.encode(), message.encode(),
                 hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Outbound — real contact upsert
# ---------------------------------------------------------------------------

def _contact_properties(payload: dict) -> dict:
    return {
        "email": payload["email"],
        "firstname": payload["first_name"],
        "lastname": payload["last_name"],
        "company": payload["company"],
        "jobtitle": payload.get("job_title") or "",
        "hs_lead_status": {"Hot": "OPEN_DEAL", "Warm": "IN_PROGRESS", "Cold": "UNQUALIFIED"}.get(
            payload.get("verdict") or "", "NEW"
        ),
    }


def push_contact(db: Session, lead: Lead, payload: dict) -> dict:
    """
    Create-or-update the HubSpot contact for a lead. Uses the org's OAuth
    connection when present, else the legacy private-app token. Captures the
    contact id on the lead and writes the sync log either way.
    """
    connection = get_connection(db, lead.org_id)
    if connection is not None:
        token = get_access_token(db, connection)
    elif settings.HUBSPOT_API_KEY:
        token = settings.HUBSPOT_API_KEY
    else:
        return {"crm": "hubspot", "status": "not_configured", "external_id": None}

    headers = {"Authorization": f"Bearer {token}"}
    properties = _contact_properties(payload)

    try:
        if lead.hubspot_contact_id:
            resp = requests.patch(
                f"{API_BASE}/crm/v3/objects/contacts/{lead.hubspot_contact_id}",
                headers=headers, json={"properties": properties},
                timeout=HTTP_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            contact_id, status = lead.hubspot_contact_id, "updated"
        else:
            resp = requests.post(
                f"{API_BASE}/crm/v3/objects/contacts",
                headers=headers, json={"properties": properties},
                timeout=HTTP_TIMEOUT_SECONDS,
            )
            if resp.status_code == 409:
                # Contact exists — HubSpot embeds "Existing ID: <id>" in the error
                detail = resp.json().get("message", "")
                existing_id = "".join(ch for ch in detail.split("ID:")[-1] if ch.isdigit())
                if not existing_id:
                    raise RuntimeError(f"409 without recoverable contact id: {detail[:200]}")
                patch = requests.patch(
                    f"{API_BASE}/crm/v3/objects/contacts/{existing_id}",
                    headers=headers, json={"properties": properties},
                    timeout=HTTP_TIMEOUT_SECONDS,
                )
                patch.raise_for_status()
                contact_id, status = existing_id, "updated"
            else:
                resp.raise_for_status()
                contact_id, status = str(resp.json()["id"]), "created"

        lead.hubspot_contact_id = contact_id
        if connection is not None:
            connection.last_outbound_at = utcnow()
        db.commit()
        log_sync(db, org_id=lead.org_id, direction="outbound",
                 event_type=f"contact.{status}", lead_id=lead.id,
                 external_id=contact_id, payload={"verdict": payload.get("verdict")})
        return {"crm": "hubspot", "status": status, "external_id": contact_id}

    except Exception as e:
        log.warning(f"[crm/hubspot] push failed for {lead.email}: {e}")
        log_sync(db, org_id=lead.org_id, direction="outbound",
                 event_type="contact.push_failed", lead_id=lead.id,
                 success=False, error=str(e))
        return {"crm": "hubspot", "status": "failed", "external_id": None}


# ---------------------------------------------------------------------------
# Inbound — webhook events → conversion_status
# ---------------------------------------------------------------------------

def _fetch_contact_email(token: str, contact_id: str) -> str | None:
    resp = requests.get(
        f"{API_BASE}/crm/v3/objects/contacts/{contact_id}",
        headers={"Authorization": f"Bearer {token}"},
        params={"properties": "email"},
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    if not resp.ok:
        return None
    return (resp.json().get("properties") or {}).get("email")


def _deal_contact_ids(token: str, deal_id: str) -> list[str]:
    resp = requests.get(
        f"{API_BASE}/crm/v3/objects/deals/{deal_id}/associations/contacts",
        headers={"Authorization": f"Bearer {token}"},
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    if not resp.ok:
        return []
    return [str(r.get("id") or r.get("toObjectId")) for r in resp.json().get("results", [])]


def _resolve_lead(db: Session, connection: CrmConnection, contact_id: str) -> Lead | None:
    q = db.query(Lead).filter(Lead.hubspot_contact_id == str(contact_id))
    if connection.org_id is not None:
        q = q.filter(Lead.org_id == connection.org_id)
    lead = q.first()
    if lead is not None:
        return lead

    # First time we hear about this contact — resolve by email and remember
    try:
        token = get_access_token(db, connection)
        email = _fetch_contact_email(token, str(contact_id))
    except Exception as e:
        log.debug(f"[crm/hubspot] contact lookup failed for {contact_id}: {e}")
        return None
    if not email:
        return None
    q = db.query(Lead).filter(Lead.email.ilike(email))
    if connection.org_id is not None:
        q = q.filter(Lead.org_id == connection.org_id)
    lead = q.first()
    if lead is not None:
        lead.hubspot_contact_id = str(contact_id)
        db.commit()
    return lead


def _apply_conversion(db: Session, lead: Lead, new_status: str, source: str) -> bool:
    """CRM wins on conversion_status; scores/verdicts are never touched."""
    if lead.conversion_status == new_status:
        return False
    old = lead.conversion_status
    lead.conversion_status = new_status
    lead.conversion_updated_at = utcnow()
    db.add(LeadHistory(
        lead_id=lead.id, event_type="conversion_updated",
        old_value=old, new_value=new_status,
    ))
    db.commit()
    try:
        from app.database import crud
        crud.append_lead_event(db, lead.id, "crm.conversion_synced", payload={
            "old": old, "new": new_status, "source": source,
        }, agent_name="hubspot_sync")
    except Exception:
        pass
    log.info(f"[crm/hubspot] {lead.email}: conversion {old} → {new_status} ({source})")
    return True


def process_webhook_events(db: Session, events: list[dict]) -> dict:
    """
    Apply a batch of HubSpot webhook events. Unknown portals, unmapped
    stages, and contacts we never touched are skipped — inbound sync must
    never invent leads.
    """
    processed = updated = skipped = 0

    for event in events:
        processed += 1
        portal_id = str(event.get("portalId", ""))
        connection = (
            db.query(CrmConnection)
            .filter(CrmConnection.portal_id == portal_id, CrmConnection.is_active.is_(True))
            .first()
        )
        if connection is None:
            skipped += 1
            continue

        subscription = event.get("subscriptionType", "")
        object_id = str(event.get("objectId", ""))
        new_value = str(event.get("propertyValue", "") or "").lower()

        try:
            if subscription == "contact.propertyChange" and event.get("propertyName") == "lifecyclestage":
                new_status = LIFECYCLE_TO_CONVERSION.get(new_value)
                if new_status is None:
                    skipped += 1
                    continue
                lead = _resolve_lead(db, connection, object_id)
                if lead is None:
                    skipped += 1
                    continue
                changed = _apply_conversion(db, lead, new_status, f"lifecyclestage={new_value}")
                updated += 1 if changed else 0
                log_sync(db, org_id=connection.org_id, direction="inbound",
                         event_type="contact.lifecyclestage", lead_id=lead.id,
                         external_id=object_id,
                         payload={"value": new_value, "applied": changed})

            elif subscription == "deal.propertyChange" and event.get("propertyName") == "dealstage":
                new_status = DEALSTAGE_TO_CONVERSION.get(new_value)
                if new_status is None:
                    skipped += 1
                    continue
                token = get_access_token(db, connection)
                touched = False
                for contact_id in _deal_contact_ids(token, object_id):
                    lead = _resolve_lead(db, connection, contact_id)
                    if lead is None:
                        continue
                    changed = _apply_conversion(db, lead, new_status, f"dealstage={new_value}")
                    log_sync(db, org_id=connection.org_id, direction="inbound",
                             event_type="deal.dealstage", lead_id=lead.id,
                             external_id=object_id,
                             payload={"value": new_value, "applied": changed})
                    touched = touched or changed
                updated += 1 if touched else 0

            else:
                skipped += 1
                continue

            connection.last_inbound_at = utcnow()
            db.commit()

        except Exception as e:
            log.warning(f"[crm/hubspot] event failed ({subscription}/{object_id}): {e}")
            log_sync(db, org_id=connection.org_id, direction="inbound",
                     event_type=subscription or "unknown", external_id=object_id,
                     success=False, error=str(e))

    return {"processed": processed, "updated": updated, "skipped": skipped}
