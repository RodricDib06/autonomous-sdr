"""
Runtime configuration toggles (Slack, enrichment provider).

Extracted from app/main.py, which had grown to ~3.5k lines and 87 endpoints.
Route order matters in FastAPI — concrete paths must be registered before the
`/{lead_id}` style catch-alls — and that is far easier to keep right in a
file scoped to one concern.
"""

import json  # noqa: F401
import re  # noqa: F401
import asyncio  # noqa: F401
from fastapi import APIRouter, Depends, HTTPException, Query, Request, BackgroundTasks  # noqa: F401
from fastapi.responses import Response, RedirectResponse, StreamingResponse  # noqa: F401
from sqlalchemy.orm import Session  # noqa: F401
import structlog

from app.services.slack_notifier import slack_notifier  # noqa: F401

from app.database.connection import get_db  # noqa: F401
from app.database import crud  # noqa: F401
from app.database.models import Lead, Enrichment, Verdict, User  # noqa: F401
from app.auth.dependencies import require_admin, require_manager, require_rep  # noqa: F401
from app.config import settings  # noqa: F401
from app.utils.time import utcnow  # noqa: F401
from app.services.queue_service import push_lead_job, get_redis  # noqa: F401

log = structlog.get_logger(__name__)

router = APIRouter(tags=["config"])


@router.get("/config/slack")
def get_slack_config(current_user: User = Depends(require_admin)):
    """Get current Slack webhook configuration"""
    return {
        "configured": slack_notifier.enabled,
        "webhook_url": "***" if slack_notifier.webhook_url else None
    }

@router.post("/config/slack")
def set_slack_config(
    current_user: User = Depends(require_admin),
    webhook_url: str = Query(...),
):
    """Set Slack webhook URL for notifications"""
    try:
        global slack_webhook_url

        if not webhook_url or len(webhook_url) == 0:
            raise HTTPException(status_code=400, detail="Webhook URL cannot be empty")

        # Validate webhook URL format
        if not webhook_url.startswith('https://hooks.slack.com/'):
            raise HTTPException(
                status_code=400,
                detail="Invalid webhook URL format. Must be from hooks.slack.com"
            )

        slack_notifier.set_webhook(webhook_url)
        slack_webhook_url = webhook_url

        log.info("slack.webhook.configured")

        return {
            "status": "success",
            "message": "Slack webhook configured",
            "configured": True
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error("Failed to set Slack webhook", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to configure Slack")

@router.post("/config/slack/test")
def test_slack_webhook(current_user: User = Depends(require_admin)):
    """Test Slack webhook connectivity"""
    try:
        if not slack_notifier.enabled:
            raise HTTPException(
                status_code=400,
                detail="Slack webhook not configured"
            )

        success = slack_notifier.test_webhook()

        return {
            "status": "success" if success else "failed",
            "message": "Webhook test successful" if success else "Webhook test failed",
            "configured": slack_notifier.enabled
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error("Failed to test Slack webhook", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to test webhook")

@router.get("/config/enrichment-provider")
def get_enrichment_provider(current_user: User = Depends(require_admin)):
    """Return the active enrichment provider."""
    return {"enrichment_provider": settings.ENRICHMENT_PROVIDER}

@router.post("/config/enrichment-provider")
def set_enrichment_provider(
    provider: str = Query(..., description="synthetic | hunter | pdl"),
    current_user: User = Depends(require_admin),
):
    """
    Toggle enrichment provider at runtime — no restart required.

    Providers:
      synthetic — default, free, heuristic (great for demos)
      hunter    — Hunter.io real company data (25 free lookups/month)
      pdl       — People Data Labs (100 free lookups/month)
    """
    _valid = {"synthetic", "hunter", "pdl"}
    if provider not in _valid:
        raise HTTPException(status_code=400, detail=f"Unknown provider. Valid options: {', '.join(sorted(_valid))}")
    settings.ENRICHMENT_PROVIDER = provider
    log.info("config.enrichment_provider.updated", provider=provider, changed_by=current_user.email)
    return {"status": "updated", "enrichment_provider": provider}

@router.post("/config/slack/disable")
def disable_slack(current_user: User = Depends(require_admin)):
    """Disable Slack notifications"""
    try:
        global slack_webhook_url
        slack_notifier.set_webhook(None)
        slack_webhook_url = None

        log.info("slack.webhook.disabled")

        return {
            "status": "success",
            "message": "Slack notifications disabled",
            "configured": False
        }
    except Exception as e:
        log.error("Failed to disable Slack", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to disable Slack")
