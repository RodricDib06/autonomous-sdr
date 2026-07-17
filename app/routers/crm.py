"""
CRM sync API — connect HubSpot, receive its webhooks, inspect the sync log.

The webhook endpoint is public by necessity (HubSpot calls it); authenticity
comes from the X-HubSpot-Signature-v3 HMAC, not a bearer token, and events
are matched to orgs via the connected portal id.
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.auth.dependencies import require_manager, require_rep
from app.config import settings
from app.database.connection import get_db
from app.database.models import CrmConnection, CrmSyncLog, User
from app.services.hubspot_sync import (
    build_authorize_url,
    create_state,
    decode_state,
    exchange_code,
    fetch_portal_id,
    get_connection,
    hubspot_oauth_configured,
    process_webhook_events,
    validate_signature_v3,
)
log = logging.getLogger(__name__)

router = APIRouter(tags=["crm"])


# ── OAuth flow ───────────────────────────────────────────────────────────────

@router.get("/crm/hubspot/start")
def start_hubspot_oauth(
    redirect_uri: str | None = None,
    current_user: User = Depends(require_manager),
):
    if not hubspot_oauth_configured():
        raise HTTPException(
            status_code=400,
            detail="HubSpot OAuth is not configured — set HUBSPOT_CLIENT_ID/_CLIENT_SECRET",
        )
    redirect_uri = redirect_uri or (
        f"{settings.APP_BASE_URL}/crm/hubspot/callback" if settings.APP_BASE_URL else ""
    )
    if not redirect_uri:
        raise HTTPException(status_code=400, detail="Set APP_BASE_URL or pass redirect_uri")
    state = create_state(current_user.id, current_user.org_id, redirect_uri)
    return {"authorize_url": build_authorize_url(state, redirect_uri), "state": state}


@router.get("/crm/hubspot/callback")
def hubspot_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    from app.services.mailbox_service import encrypt_secret

    if error:
        raise HTTPException(status_code=400, detail=f"HubSpot returned an error: {error}")
    if not code or not state:
        raise HTTPException(status_code=422, detail="Missing code or state")
    try:
        payload = decode_state(state)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        blob = exchange_code(code, payload["redirect_uri"])
        portal_id = fetch_portal_id(blob["access_token"])
    except Exception as e:
        log.warning(f"[crm] HubSpot OAuth exchange failed: {e}")
        raise HTTPException(status_code=502, detail=f"OAuth exchange failed: {e}")

    org_id = payload.get("org")
    connection = get_connection(db, org_id)
    if connection is not None:
        connection.token_encrypted = encrypt_secret(json.dumps(blob))
        connection.portal_id = portal_id
        connection.is_active = True
    else:
        connection = CrmConnection(
            org_id=org_id, provider="hubspot", portal_id=portal_id,
            token_encrypted=encrypt_secret(json.dumps(blob)),
            connected_by_id=payload.get("sub"),
        )
        db.add(connection)
    db.commit()
    log.info(f"[crm] HubSpot portal {portal_id} connected for org {org_id}")
    return {"status": "connected", "portal_id": portal_id}


# ── Status / log / disconnect ────────────────────────────────────────────────

@router.get("/crm/status")
def crm_status(
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    connection = get_connection(db, current_user.org_id)
    return {
        "hubspot": {
            "oauth_configured": hubspot_oauth_configured(),
            "connected": connection is not None,
            "portal_id": connection.portal_id if connection else None,
            "last_outbound_at": connection.last_outbound_at.isoformat()
            if connection and connection.last_outbound_at else None,
            "last_inbound_at": connection.last_inbound_at.isoformat()
            if connection and connection.last_inbound_at else None,
            "legacy_api_key": bool(settings.HUBSPOT_API_KEY),
        }
    }


@router.get("/crm/log")
def crm_log(
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=200),
):
    q = db.query(CrmSyncLog)
    if current_user.org_id is not None:
        q = q.filter(CrmSyncLog.org_id == current_user.org_id)
    entries = q.order_by(CrmSyncLog.created_at.desc()).limit(limit).all()
    return {
        "entries": [
            {
                "direction": e.direction,
                "event_type": e.event_type,
                "lead_id": e.lead_id,
                "external_id": e.external_id,
                "payload": e.payload,
                "success": e.success,
                "error_message": e.error_message,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ]
    }


@router.delete("/crm/hubspot")
def disconnect_hubspot(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    connection = get_connection(db, current_user.org_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="No HubSpot connection")
    connection.is_active = False
    db.commit()
    return {"status": "disconnected"}


# ── Inbound webhook ──────────────────────────────────────────────────────────

@router.post("/ingest/hubspot-webhook")
async def hubspot_webhook(request: Request, db: Session = Depends(get_db)):
    """
    HubSpot webhook receiver (contact.propertyChange/lifecyclestage,
    deal.propertyChange/dealstage). Signature-validated; stale or unsigned
    requests are rejected before any parsing side effects.
    """
    body = await request.body()
    signature = request.headers.get("X-HubSpot-Signature-v3", "")
    timestamp = request.headers.get("X-HubSpot-Request-Timestamp", "")

    if not validate_signature_v3("POST", str(request.url), body, timestamp, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        events = json.loads(body)
        if not isinstance(events, list):
            raise ValueError("expected a JSON array of events")
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=422, detail=f"Malformed webhook body: {e}")

    summary = process_webhook_events(db, events)
    if summary["updated"]:
        log.info(f"[crm] HubSpot webhook: {summary}")
    return summary
