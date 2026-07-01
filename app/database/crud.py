from sqlalchemy.orm import Session
from app.database.models import Lead, Enrichment, Verdict, AgentLog, LeadEvent


def create_lead(db: Session, name: str, email: str, company: str, source: str = "webhook") -> Lead:
    lead = Lead(name=name, email=email, company=company, source=source)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def get_lead(db: Session, lead_id: str) -> Lead | None:
    return db.query(Lead).filter(Lead.id == lead_id).first()


def get_all_leads(db: Session, limit: int = 100) -> list[Lead]:
    return db.query(Lead).order_by(Lead.created_at.desc()).limit(limit).all()


def update_lead_status(db: Session, lead_id: str, status: str) -> None:
    from datetime import datetime
    db.query(Lead).filter(Lead.id == lead_id).update({"status": status, "updated_at": datetime.utcnow()})
    db.commit()


def create_enrichment(db: Session, lead_id: str, data: dict) -> Enrichment:
    enrichment = Enrichment(lead_id=lead_id, **data)
    db.add(enrichment)
    db.commit()
    db.refresh(enrichment)
    return enrichment


def create_verdict(db: Session, lead_id: str, enrichment_id: str, data: dict) -> Verdict:
    verdict = Verdict(lead_id=lead_id, enrichment_id=enrichment_id, **data)
    db.add(verdict)
    db.commit()
    db.refresh(verdict)
    return verdict


def get_verdict_by_lead(db: Session, lead_id: str) -> Verdict | None:
    return db.query(Verdict).filter(Verdict.lead_id == lead_id).first()


def update_verdict(db: Session, verdict_id: str, data: dict) -> None:
    db.query(Verdict).filter(Verdict.id == verdict_id).update(data)
    db.commit()


def append_lead_event(
    db: Session,
    lead_id: str,
    event_type: str,
    payload: dict | None = None,
    agent_name: str | None = None,
) -> LeadEvent:
    """Append an immutable event to the lead event log."""
    event = LeadEvent(
        lead_id=lead_id,
        event_type=event_type,
        agent_name=agent_name,
        payload=payload or {},
    )
    db.add(event)
    db.commit()
    return event


def create_agent_log(
    db: Session,
    lead_id: str,
    agent_name: str,
    input_data: dict,
    output_data: dict | None,
    duration_ms: int,
    success: bool,
    error_message: str | None = None,
) -> AgentLog:
    log = AgentLog(
        lead_id=lead_id,
        agent_name=agent_name,
        input_data=input_data,
        output_data=output_data,
        duration_ms=duration_ms,
        success=success,
        error_message=error_message,
    )
    db.add(log)
    db.commit()
    return log
