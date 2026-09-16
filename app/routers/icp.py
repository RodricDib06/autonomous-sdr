"""
Ideal Customer Profile configuration and preview.

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

from app.database.connection import get_db  # noqa: F401
from app.database import crud  # noqa: F401
from app.database.models import Lead, Enrichment, Verdict, User  # noqa: F401
from app.auth.dependencies import require_admin, require_manager, require_rep  # noqa: F401
from app.config import settings  # noqa: F401
from app.utils.time import utcnow  # noqa: F401
from app.services.queue_service import push_lead_job, get_redis  # noqa: F401

log = structlog.get_logger(__name__)

router = APIRouter(tags=["icp"])


@router.get("/icp")
def get_icp(
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Return the current ICP configuration."""
    from app.services.icp_service import get_icp_config
    cfg = get_icp_config(db, org_id=current_user.org_id)
    if cfg is None:
        return {
            "configured": False,
            "industries": [],
            "seniority_levels": [],
            "excluded_industries": [],
            "min_employees": None,
            "max_employees": None,
            "updated_at": None,
            "updated_by_id": None,
        }
    return {
        "configured": True,
        "industries": cfg.industries or [],
        "seniority_levels": cfg.seniority_levels or [],
        "excluded_industries": cfg.excluded_industries or [],
        "min_employees": cfg.min_employees,
        "max_employees": cfg.max_employees,
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
        "updated_by_id": cfg.updated_by_id,
    }

@router.put("/icp")
def update_icp(
    payload: dict,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """
    Create or update the ICP configuration.
    Accepted fields: industries, seniority_levels, excluded_industries,
                     min_employees, max_employees
    """
    from app.services.icp_service import upsert_icp_config

    allowed = {
        "industries", "seniority_levels", "excluded_industries",
        "min_employees", "max_employees",
    }
    fields = {k: v for k, v in payload.items() if k in allowed}

    # Validate types
    for list_field in ("industries", "seniority_levels", "excluded_industries"):
        if list_field in fields:
            if fields[list_field] is None:
                fields[list_field] = []
            elif not isinstance(fields[list_field], list):
                raise HTTPException(status_code=422, detail=f"{list_field} must be a list")

    for int_field in ("min_employees", "max_employees"):
        if int_field in fields and fields[int_field] is not None:
            try:
                fields[int_field] = int(fields[int_field])
                if fields[int_field] < 0:
                    raise ValueError
            except (ValueError, TypeError):
                raise HTTPException(status_code=422, detail=f"{int_field} must be a non-negative integer")

    if not fields:
        raise HTTPException(status_code=422, detail="No valid fields provided")

    cfg = upsert_icp_config(db, user_id=current_user.id, org_id=current_user.org_id, **fields)
    return {
        "configured": True,
        "industries": cfg.industries or [],
        "seniority_levels": cfg.seniority_levels or [],
        "excluded_industries": cfg.excluded_industries or [],
        "min_employees": cfg.min_employees,
        "max_employees": cfg.max_employees,
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
        "updated_by_id": cfg.updated_by_id,
    }

@router.get("/icp/preview")
def get_icp_preview(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Return counts of leads matching the current ICP — used for live preview."""
    from app.services.icp_service import icp_match_counts
    return icp_match_counts(db)
