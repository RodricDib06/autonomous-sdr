import logging
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.database.connection import get_db, create_all_tables
from app.database import crud
from app.database.models import Lead, Enrichment, Verdict
from app.services.queue_service import push_lead_job, get_redis
from app.services.ollama_client import OllamaConnectionError
from app.services.deduplication import DeduplicationService
from app.services.csv_import import CSVImportService
from app.services.validation import EmailDomainValidator
from app.services.slack_notifier import SlackNotifier
from app.services.data_quality import DataQualityService
from app.services.export_service import build_export_rows, to_csv_bytes, to_hubspot_rows, to_salesforce_rows
from app.services.batch_service import execute_batch
from app.schemas.lead import LeadCreate, LeadResponse, LeadDetail, BatchRequest, ImportHistoryResponse, AssignRequest, ConversionRequest, LeadHistoryEntry, AssignmentStats
from app.auth.dependencies import get_current_user, require_admin, require_manager, require_rep
from app.database.models import User
from app.routers.auth import router as auth_router
from app.config import settings
from fastapi import UploadFile, File
from fastapi.responses import Response

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: Create tables and validate dependencies
    Shutdown: Cleanup if needed
    """
    try:
        import os as _os
        _testing = bool(_os.getenv("TESTING"))

        log.info("AutonomousSDR starting up...")
        if not _testing:
            create_all_tables()

        # Validate Redis connection (skipped in test mode)
        if not _testing:
            try:
                redis = get_redis()
                redis.ping()
                log.info("✓ Redis connection OK")
            except Exception as e:
                log.error(f"✗ Redis connection failed: {e}")
                raise
        
        # Validate Ollama connection (optional — skipped in test mode)
        if not _testing:
            try:
                from app.services.ollama_client import OllamaClient
                client = OllamaClient()
                client.generate("test")
                log.info("✓ Ollama connection OK")
            except OllamaConnectionError as e:
                log.warning(f"⚠ Ollama not ready yet: {e}. Will retry on first request.")
        
        # Seed initial admin if no users exist (skipped in test mode)
        if not _testing:
            try:
                from app.database.connection import SessionLocal
                from app.database.models import User as UserModel
                from app.services.auth_service import hash_password
                import uuid
                db_seed = SessionLocal()
                try:
                    if db_seed.query(UserModel).count() == 0:
                        admin = UserModel(
                            id=str(uuid.uuid4()),
                            email=settings.INITIAL_ADMIN_EMAIL,
                            password_hash=hash_password(settings.INITIAL_ADMIN_PASSWORD),
                            role="admin",
                        )
                        db_seed.add(admin)
                        db_seed.commit()
                        log.info(f"✓ Initial admin created: {settings.INITIAL_ADMIN_EMAIL}")
                    else:
                        log.info("✓ Users table already populated — skipping admin seed")
                finally:
                    db_seed.close()
            except Exception as e:
                log.warning(f"⚠ Admin seed skipped (auth tables may not exist yet): {e}")

        log.info("AutonomousSDR ready to accept leads")
        yield

        log.info("AutonomousSDR shutting down...")
    except Exception as e:
        log.critical(f"Startup failed: {e}")
        raise


app = FastAPI(title="AutonomousSDR", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "Accept", "Origin"],
)

app.include_router(auth_router)

# Global Slack notifier
slack_notifier = SlackNotifier()
# Store webhook URL in memory (in production, use database)
slack_webhook_url = None


@app.get("/health")
def health_check():
    from app.services.queue_service import get_worker_status
    worker = get_worker_status()
    return {
        "status": "healthy",
        "service": "AutonomousSDR",
        "version": "1.0.0",
        "worker_active": worker["worker_active"],
        "worker_last_seen": worker["worker_last_seen"],
    }


@app.post("/leads", response_model=LeadResponse)
def receive_lead(
    payload: LeadCreate,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Submit a new lead for qualification"""
    try:
        lead = crud.create_lead(
            db,
            name=payload.name,
            email=payload.email,
            company=payload.company,
            source=payload.source,
        )
        push_lead_job(lead.id)
        log.info(f"Lead created: {lead.id} ({lead.email})")
        return lead
    except Exception as e:
        log.error(f"Failed to create lead: {e}")
        raise HTTPException(status_code=500, detail="Failed to create lead")


@app.get("/leads", response_model=list[LeadResponse])
def list_leads(
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    """List all leads with pagination"""
    try:
        leads = db.query(Lead).order_by(
            Lead.created_at.desc()
        ).offset(skip).limit(limit).all()
        return leads
    except Exception as e:
        log.error(f"Failed to list leads: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch leads")


@app.get("/leads/stats")
def get_lead_stats(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Get statistics about processed leads"""
    try:
        total_leads = db.query(Lead).count()
        completed_leads = db.query(Lead).filter(Lead.status == "complete").count()
        failed_leads = db.query(Lead).filter(Lead.status == "failed").count()
        processing_leads = db.query(Lead).filter(Lead.status == "processing").count()
        
        # Verdict breakdown
        hot_leads = db.query(Verdict).filter(Verdict.final_verdict == "Hot").count()
        warm_leads = db.query(Verdict).filter(Verdict.final_verdict == "Warm").count()
        cold_leads = db.query(Verdict).filter(Verdict.final_verdict == "Cold").count()
        
        return {
            "total_leads": total_leads,
            "completed": completed_leads,
            "failed": failed_leads,
            "processing": processing_leads,
            "success_rate": completed_leads / total_leads if total_leads > 0 else 0,
            "verdict_breakdown": {
                "hot": hot_leads,
                "warm": warm_leads,
                "cold": cold_leads
            }
        }
    except Exception as e:
        log.error(f"Failed to get stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get statistics")


@app.get("/leads/quality-report")
def get_quality_report(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Get system-wide data quality summary"""
    try:
        report = DataQualityService().get_quality_report(db)
        return report
    except Exception as e:
        log.error(f"Failed to get quality report: {e}")
        raise HTTPException(status_code=500, detail="Failed to get quality report")


@app.post("/leads/quality-backfill")
def backfill_quality_scores(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Score all leads that have never been quality-scored."""
    try:
        unscored = db.query(Lead).filter(Lead.data_quality_score.is_(None)).all()
        service = DataQualityService()
        for lead in unscored:
            service.update_lead_quality(db, lead)
        log.info(f"Quality backfill complete: {len(unscored)} leads scored")
        return {"scored": len(unscored)}
    except Exception as e:
        log.error(f"Quality backfill failed: {e}")
        raise HTTPException(status_code=500, detail="Quality backfill failed")


@app.get("/leads/hot")
def get_hot_leads(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
):
    """Get high-priority (Hot) leads ready for sales follow-up"""
    try:
        hot_leads = db.query(Lead).join(Verdict).filter(
            Lead.status == "complete",
            Verdict.final_verdict == "Hot"
        ).order_by(Verdict.confidence_score.desc()).limit(limit).all()
        
        results = []
        for lead in hot_leads:
            verdict = lead.verdicts[0] if lead.verdicts else None
            enrichment = lead.enrichments[0] if lead.enrichments else None
            
            results.append({
                "id": lead.id,
                "name": lead.name,
                "email": lead.email,
                "company": lead.company,
                "confidence": verdict.confidence_score if verdict else 0,
                "job_title": enrichment.job_title if enrichment else None,
                "seniority": enrichment.seniority if enrichment else None,
                "industry": enrichment.industry if enrichment else None,
                "reasoning": verdict.analysis_reasoning if verdict else None
            })
        
        return {"hot_leads": results, "count": len(results)}
    except Exception as e:
        log.error(f"Failed to get hot leads: {e}")
        raise HTTPException(status_code=500, detail="Failed to get hot leads")


@app.get("/leads/export")
def export_leads(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
    verdict_filter: str = Query(None, description="Filter by verdict: Hot, Warm, Cold"),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0, description="Minimum confidence score"),
    industry_filter: str = Query(None, description="Filter by industry (partial match)"),
    format: str = Query("json", description="Output format: json, csv, hubspot, salesforce"),
):
    """Export leads data — supports JSON and CRM-formatted CSV (HubSpot, Salesforce)."""
    try:
        query = db.query(Lead).filter(Lead.status == "complete", Lead.archived == False)

        if verdict_filter:
            query = query.join(Verdict).filter(Verdict.final_verdict == verdict_filter)
        elif min_confidence > 0:
            query = query.join(Verdict).filter(Verdict.confidence_score >= min_confidence)

        if industry_filter:
            query = query.join(Enrichment, Enrichment.lead_id == Lead.id, isouter=True).filter(
                Enrichment.industry.ilike(f"%{industry_filter}%")
            )

        leads = query.order_by(Lead.created_at.desc()).all()
        rows = build_export_rows(leads)

        if format == "json":
            return {
                "export": rows,
                "count": len(rows),
                "filters": {
                    "verdict": verdict_filter,
                    "min_confidence": min_confidence,
                    "industry": industry_filter,
                    "format": format,
                },
            }

        if format == "hubspot":
            csv_rows = to_hubspot_rows(rows)
            filename = "leads_hubspot.csv"
        elif format == "salesforce":
            csv_rows = to_salesforce_rows(rows)
            filename = "leads_salesforce.csv"
        elif format == "csv":
            csv_rows = rows
            filename = "leads.csv"
        else:
            raise HTTPException(status_code=400, detail=f"Unknown format '{format}'. Use: json, csv, hubspot, salesforce")

        csv_bytes = to_csv_bytes(csv_rows)
        return Response(
            content=csv_bytes,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to export leads: {e}")
        raise HTTPException(status_code=500, detail="Failed to export leads")


# ============================================================================
# PHASE 1 FEATURES: Deduplication, CSV Import, Validation, Slack Alerts
# ============================================================================

@app.post("/leads/import-csv")
def import_csv_leads(
    file: UploadFile = File(...),
    current_user: User = Depends(require_manager),
    check_duplicates: bool = Query(True),
    db: Session = Depends(get_db),
):
    """Import leads from CSV file"""
    try:
        # Read CSV content
        content = file.file.read().decode('utf-8')
        file.file.close()
        
        # Import using CSVImportService
        import_service = CSVImportService(db)
        result = import_service.import_leads(content, check_duplicates=check_duplicates)

        # Persist import audit record
        import_service.persist_history(db, file.filename or "unknown.csv", result)

        # Send Slack notification if configured
        if slack_notifier.enabled:
            slack_notifier.notify_import_complete(result.to_dict())

        log.info(f"CSV import completed: {result.successful} successful, {result.failed} failed")

        return result.to_dict()
    
    except Exception as e:
        log.error(f"Failed to import CSV: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to import CSV: {str(e)}")


@app.get("/leads/duplicates/report")
def get_duplicate_report(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Get report of potential duplicate leads in system"""
    try:
        dedup_service = DeduplicationService(db)
        report = dedup_service.get_duplicate_report()
        
        return {
            "report": report,
            "generated_at": datetime.utcnow().isoformat()
        }
    except Exception as e:
        log.error(f"Failed to generate duplicate report: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate duplicate report")


@app.get("/leads/import-history")
def get_import_history(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
):
    """List past CSV import operations, newest first."""
    try:
        from app.database.models import ImportHistory
        records = (
            db.query(ImportHistory)
            .order_by(ImportHistory.started_at.desc())
            .limit(limit)
            .all()
        )
        return {
            "imports": [ImportHistoryResponse.model_validate(r).model_dump() for r in records],
            "count": len(records),
        }
    except Exception as e:
        log.error(f"Failed to get import history: {e}")
        raise HTTPException(status_code=500, detail="Failed to get import history")


@app.post("/leads/reprocess-failed")
def reprocess_failed(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Re-queue all failed leads back into the processing pipeline."""
    from app.services.queue_service import push_lead_job
    from datetime import datetime
    failed = db.query(Lead).filter(Lead.status == "failed").all()
    if not failed:
        return {"requeued": 0, "message": "No failed leads found"}
    now = datetime.utcnow()
    for lead in failed:
        lead.status = "processing"
        lead.updated_at = now
        push_lead_job(lead.id)
    db.commit()
    log.info(f"Reprocessing {len(failed)} failed leads (triggered by {current_user.email})")
    return {"requeued": len(failed), "message": f"{len(failed)} leads re-queued for processing"}


@app.post("/leads/batch")
def batch_leads(
    request: BatchRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Perform a bulk action on multiple leads at once."""
    try:
        result = execute_batch(db, request.action, request.lead_ids, request.payload)
        return result.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error(f"Batch action '{request.action}' failed: {e}")
        raise HTTPException(status_code=500, detail="Batch action failed")


@app.post("/leads/{lead_id}/assign")
def assign_lead_endpoint(
    lead_id: str,
    request: AssignRequest,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Assign a lead to a sales rep."""
    try:
        from app.services.assignment_service import assign_lead
        lead = assign_lead(db, lead_id, request.rep_id, changed_by_id=current_user.id)
        log.info(f"Lead {lead_id} assigned to rep {request.rep_id} by {current_user.email}")
        return {"success": True, "lead_id": lead_id, "assigned_to_id": lead.assigned_to_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error(f"Failed to assign lead: {e}")
        raise HTTPException(status_code=500, detail="Failed to assign lead")


@app.delete("/leads/{lead_id}/assign")
def unassign_lead_endpoint(
    lead_id: str,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Unassign a lead from its sales rep."""
    try:
        from app.services.assignment_service import unassign_lead
        unassign_lead(db, lead_id, changed_by_id=current_user.id)
        log.info(f"Lead {lead_id} unassigned by {current_user.email}")
        return {"success": True, "lead_id": lead_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error(f"Failed to unassign lead: {e}")
        raise HTTPException(status_code=500, detail="Failed to unassign lead")


@app.post("/leads/{lead_id}/conversion")
def update_conversion_status_endpoint(
    lead_id: str,
    request: ConversionRequest,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Update lead conversion status."""
    try:
        from app.services.assignment_service import update_conversion_status
        lead = update_conversion_status(
            db,
            lead_id,
            request.status,
            notes=request.notes,
            changed_by_id=current_user.id,
        )
        log.info(f"Lead {lead_id} conversion status updated to '{request.status}' by {current_user.email}")
        return {"success": True, "lead_id": lead_id, "conversion_status": lead.conversion_status}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error(f"Failed to update conversion status: {e}")
        raise HTTPException(status_code=500, detail="Failed to update conversion status")


@app.get("/leads/{lead_id}/history", response_model=list[LeadHistoryEntry])
def get_lead_history_endpoint(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Get history timeline for a lead."""
    from app.services.assignment_service import get_lead_history
    return get_lead_history(db, lead_id)


@app.get("/dashboard/assignment-stats", response_model=list[AssignmentStats])
def get_assignment_stats(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Get assignment and conversion stats for all reps."""
    from app.database.models import User, Lead

    reps = db.query(User).filter(User.role == "rep", User.is_active == True).all()
    stats = []

    for rep in reps:
        assigned = db.query(Lead).filter(Lead.assigned_to_id == rep.id).count()
        contacted = db.query(Lead).filter(
            Lead.assigned_to_id == rep.id,
            Lead.conversion_status.in_(["contacted", "scheduled", "won"])
        ).count()
        won = db.query(Lead).filter(
            Lead.assigned_to_id == rep.id,
            Lead.conversion_status == "won"
        ).count()

        contacted_pct = (contacted / assigned * 100) if assigned > 0 else 0
        won_pct = (won / assigned * 100) if assigned > 0 else 0

        stats.append(
            AssignmentStats(
                rep_id=rep.id,
                rep_email=rep.email,
                assigned_count=assigned,
                contacted_count=contacted,
                contacted_pct=contacted_pct,
                won_count=won,
                won_pct=won_pct,
            )
        )

    return stats


@app.get("/leads/{lead_id}", response_model=LeadDetail)
def get_lead(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Get detailed information about a specific lead"""
    try:
        lead = crud.get_lead(db, lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")

        enrichment = lead.enrichments[0] if lead.enrichments else None
        verdict = lead.verdicts[0] if lead.verdicts else None

        detail = LeadDetail.model_validate(lead)
        if enrichment:
            detail.enrichment = {
                "job_title": enrichment.job_title,
                "seniority": enrichment.seniority,
                "company_size": enrichment.company_size,
                "industry": enrichment.industry,
                "revenue_estimate": enrichment.revenue_estimate,
                "tech_stack": enrichment.tech_stack,
                "confidence": enrichment.confidence,
                "enrichment_source": enrichment.enrichment_source,
            }
        if verdict:
            detail.verdict = {
                "analysis_verdict": verdict.analysis_verdict,
                "final_verdict": verdict.final_verdict,
                "confidence_score": verdict.confidence_score,
                "reasoning": verdict.analysis_reasoning,
                "bant_scores": verdict.bant_scores,
                "icp_match": verdict.icp_match,
                "validated": verdict.validated,
                "consistency_notes": verdict.consistency_notes,
                "flags": verdict.flags,
            }
        return detail
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to fetch lead {lead_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch lead")


@app.get("/leads/{lead_id}/quality-score")
def get_lead_quality_score(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Get data quality scores for a specific lead, recomputing live."""
    try:
        lead = crud.get_lead(db, lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")

        scores = DataQualityService().update_lead_quality(db, lead)
        return {
            "lead_id": lead_id,
            "name": lead.name,
            "email": lead.email,
            "company": lead.company,
            **scores,
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to get quality score for {lead_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get quality score")


@app.post("/leads/{lead_id}/check-duplicate")
def check_lead_duplicate(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Check if a lead has duplicates"""
    try:
        lead = crud.get_lead(db, lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        
        dedup_service = DeduplicationService(db)
        potential_dupes = dedup_service.find_potential_duplicates(
            lead.name, lead.email, lead.company
        )
        
        # Filter out the lead itself
        potential_dupes = [
            d for d in potential_dupes if d['lead'].id != lead_id
        ]
        
        return {
            "lead_id": lead_id,
            "has_duplicates": len(potential_dupes) > 0,
            "potential_duplicates": [
                {
                    "id": d['lead'].id,
                    "name": d['lead'].name,
                    "email": d['lead'].email,
                    "company": d['lead'].company,
                    "match_score": d['score'],
                    "match_type": d['match_type'],
                    "reason": d['reason']
                }
                for d in potential_dupes
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to check duplicates for {lead_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to check duplicates")


@app.post("/leads/{primary_id}/merge/{duplicate_id}")
def merge_duplicate_leads(
    primary_id: str,
    duplicate_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Merge a duplicate lead into the primary lead"""
    try:
        primary = crud.get_lead(db, primary_id)
        duplicate = crud.get_lead(db, duplicate_id)
        
        if not primary or not duplicate:
            raise HTTPException(status_code=404, detail="One or both leads not found")
        
        dedup_service = DeduplicationService(db)
        success = dedup_service.merge_leads(primary_id, duplicate_id)
        
        if success:
            log.info(f"Merged lead {duplicate_id} into {primary_id}")
            return {
                "status": "success",
                "message": f"Lead {duplicate_id} merged into {primary_id}",
                "primary_lead_id": primary_id
            }
        else:
            raise HTTPException(status_code=400, detail="Failed to merge leads")
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to merge leads {primary_id} and {duplicate_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to merge leads")


@app.post("/validate/email")
def validate_email(
    email: str = Query(...),
    current_user: User = Depends(require_rep),
):
    """Validate email format, domain, and characteristics"""
    try:
        result = EmailDomainValidator.validate_email_with_domain(email, check_mx=True)
        
        return {
            "email": email,
            "validation": result,
            "is_valid": result['email']['is_valid'],
            "is_deliverable": result['is_deliverable'],
            "overall_quality": result['overall_quality'],
            "issues": result['email']['issues'] + (result['domain']['issues'] if result['domain'] else [])
        }
    except Exception as e:
        log.error(f"Failed to validate email {email}: {e}")
        raise HTTPException(status_code=500, detail="Failed to validate email")


@app.post("/validate/email-batch")
def validate_email_batch(
    emails: list[str],
    current_user: User = Depends(require_rep),
):
    """Validate multiple emails at once"""
    try:
        results = []
        for email in emails:
            result = EmailDomainValidator.validate_email_with_domain(email, check_mx=True)
            results.append({
                "email": email,
                "is_valid": result['email']['is_valid'],
                "is_deliverable": result['is_deliverable'],
                "overall_quality": result['overall_quality'],
                "domain_type": EmailDomainValidator.get_domain_type(email)
            })
        
        return {
            "total": len(emails),
            "valid": sum(1 for r in results if r['is_valid']),
            "deliverable": sum(1 for r in results if r['is_deliverable']),
            "results": results
        }
    except Exception as e:
        log.error(f"Failed to validate email batch: {e}")
        raise HTTPException(status_code=500, detail="Failed to validate emails")


@app.get("/config/slack")
def get_slack_config(current_user: User = Depends(require_admin)):
    """Get current Slack webhook configuration"""
    return {
        "configured": slack_notifier.enabled,
        "webhook_url": "***" if slack_notifier.webhook_url else None
    }


@app.post("/config/slack")
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
        
        log.info("Slack webhook configured")
        
        return {
            "status": "success",
            "message": "Slack webhook configured",
            "configured": True
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to set Slack webhook: {e}")
        raise HTTPException(status_code=500, detail="Failed to configure Slack")


@app.post("/config/slack/test")
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
        log.error(f"Failed to test Slack webhook: {e}")
        raise HTTPException(status_code=500, detail="Failed to test webhook")


@app.post("/config/slack/disable")
def disable_slack(current_user: User = Depends(require_admin)):
    """Disable Slack notifications"""
    try:
        global slack_webhook_url
        slack_notifier.set_webhook(None)
        slack_webhook_url = None
        
        log.info("Slack notifications disabled")
        
        return {
            "status": "success",
            "message": "Slack notifications disabled",
            "configured": False
        }
    except Exception as e:
        log.error(f"Failed to disable Slack: {e}")
        raise HTTPException(status_code=500, detail="Failed to disable Slack")
