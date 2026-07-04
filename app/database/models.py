import uuid
from datetime import datetime
from sqlalchemy import String, Float, Boolean, Integer, Text, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.connection import Base


def new_uuid():
    return str(uuid.uuid4())


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), index=True)
    company: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(100), default="webhook")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="processing")
    completeness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    assigned_to_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    conversion_status: Mapped[str] = mapped_column(String(50), default="unqualified")
    conversion_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    conversion_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    decay_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_decay_check_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reengagement_count: Mapped[int] = mapped_column(Integer, default=0)
    last_trigger_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    identified_via_ip: Mapped[bool] = mapped_column(Boolean, default=False)
    lookalike_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    referred_by_lead_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("leads.id"), nullable=True)

    enrichments: Mapped[list["Enrichment"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    events: Mapped[list["LeadEvent"]] = relationship(back_populates="lead", cascade="all, delete-orphan", foreign_keys="LeadEvent.lead_id")
    verdicts: Mapped[list["Verdict"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    agent_logs: Mapped[list["AgentLog"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    history: Mapped[list["LeadHistory"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    assigned_to: Mapped["User | None"] = relationship(foreign_keys=[assigned_to_id])
    outreach_emails: Mapped[list["OutreachEmail"]] = relationship(back_populates="lead", cascade="all, delete-orphan", foreign_keys="OutreachEmail.lead_id")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="lead", cascade="all, delete-orphan", foreign_keys="Conversation.lead_id")
    booking_requests: Mapped[list["BookingRequest"]] = relationship(back_populates="lead", cascade="all, delete-orphan", foreign_keys="BookingRequest.lead_id")
    intent_signals: Mapped[list["IntentSignal"]] = relationship(back_populates="lead", cascade="all, delete-orphan", foreign_keys="IntentSignal.lead_id")


class Enrichment(Base):
    __tablename__ = "enrichments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    lead_id: Mapped[str] = mapped_column(String(36), ForeignKey("leads.id"), index=True)
    job_title: Mapped[str | None] = mapped_column(String(255))
    seniority: Mapped[str | None] = mapped_column(String(100))
    company_size: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(100))
    revenue_estimate: Mapped[str | None] = mapped_column(String(100))
    tech_stack: Mapped[dict | None] = mapped_column(JSONB)
    confidence: Mapped[float | None] = mapped_column(Float)
    enrichment_source: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lead: Mapped["Lead"] = relationship(back_populates="enrichments")


class Verdict(Base):
    __tablename__ = "verdicts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    lead_id: Mapped[str] = mapped_column(String(36), ForeignKey("leads.id"), index=True)
    enrichment_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("enrichments.id"))
    analysis_verdict: Mapped[str | None] = mapped_column(String(50))
    analysis_reasoning: Mapped[str | None] = mapped_column(Text)
    bant_scores: Mapped[dict | None] = mapped_column(JSONB)
    icp_match: Mapped[bool | None] = mapped_column(Boolean)
    validated: Mapped[bool | None] = mapped_column(Boolean)
    final_verdict: Mapped[str | None] = mapped_column(String(50))
    confidence_score: Mapped[float | None] = mapped_column(Float)
    consistency_notes: Mapped[str | None] = mapped_column(Text)
    flags: Mapped[dict | None] = mapped_column(JSONB)
    debate_transcript: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lead: Mapped["Lead"] = relationship(back_populates="verdicts")


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    lead_id: Mapped[str] = mapped_column(String(36), ForeignKey("leads.id"), index=True)
    agent_name: Mapped[str] = mapped_column(String(100))
    input_data: Mapped[dict | None] = mapped_column(JSONB)
    output_data: Mapped[dict | None] = mapped_column(JSONB)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lead: Mapped["Lead"] = relationship(back_populates="agent_logs")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="rep")  # admin | manager | rep
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    api_keys: Mapped[list["APIKey"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))          # human label e.g. "CI Pipeline"
    key_prefix: Mapped[str] = mapped_column(String(12))     # first 12 chars of raw key (for display)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # SHA-256 hex
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="api_keys")


class ImportHistory(Base):
    __tablename__ = "import_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    filename: Mapped[str] = mapped_column(String(255))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    successful: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    imported_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class LeadHistory(Base):
    __tablename__ = "lead_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    lead_id: Mapped[str] = mapped_column(String(36), ForeignKey("leads.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(50))  # status_changed, assigned, verdict_updated, conversion_updated
    old_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    new_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    changed_by_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    lead: Mapped["Lead"] = relationship(back_populates="history")
    changed_by: Mapped["User | None"] = relationship(foreign_keys=[changed_by_id])


# ---------------------------------------------------------------------------
# Compliance — do-not-contact suppression list
# ---------------------------------------------------------------------------

class SuppressionEntry(Base):
    """
    An email address or whole domain that must never be contacted.

    Populated by: the one-click unsubscribe link, unsubscribe-intent detection
    on inbound replies, hard bounces, or manual entry by a manager.
    Checked before every outreach send (initial and scheduled follow-ups).
    """
    __tablename__ = "suppression_list"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    # Lower-cased email ("jane@acme.com") or bare domain ("acme.com")
    value: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(20), default="email")  # email | domain
    # unsubscribe_link | reply_keyword | bounce | manual | gdpr_request
    source: Mapped[str] = mapped_column(String(50), default="manual")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    lead_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("leads.id"), nullable=True)
    created_by_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


# ---------------------------------------------------------------------------
# Outreach
# ---------------------------------------------------------------------------

class OutreachSequence(Base):
    """A named multi-step email sequence, optionally tagged for A/B testing."""
    __tablename__ = "outreach_sequences"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(255))
    # steps: list of {step: int, delay_days: int, subject_template: str, body_template: str}
    steps: Mapped[list] = mapped_column(JSONB, default=list)
    ab_variant: Mapped[str | None] = mapped_column(String(10), nullable=True)  # "A", "B", etc.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    emails: Mapped[list["OutreachEmail"]] = relationship(back_populates="sequence", cascade="all, delete-orphan")


class OutreachEmail(Base):
    """A single email in a sequence — scheduled, sent, or failed."""
    __tablename__ = "outreach_emails"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    lead_id: Mapped[str] = mapped_column(String(36), ForeignKey("leads.id"), index=True)
    sequence_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("outreach_sequences.id"), nullable=True)
    step_number: Mapped[int] = mapped_column(Integer, default=1)
    subject: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    # status: scheduled | sent | opened | clicked | replied | bounced | failed
    status: Mapped[str] = mapped_column(String(50), default="scheduled")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_flags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    quality_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lead: Mapped["Lead"] = relationship(back_populates="outreach_emails", foreign_keys=[lead_id])
    sequence: Mapped["OutreachSequence | None"] = relationship(back_populates="emails")


# ---------------------------------------------------------------------------
# Conversations (agent memory)
# ---------------------------------------------------------------------------

class Conversation(Base):
    """Agent memory — full message history for a lead across any channel."""
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    lead_id: Mapped[str] = mapped_column(String(36), ForeignKey("leads.id"), index=True)
    # channel: email | sms | chat | linkedin | internal
    channel: Mapped[str] = mapped_column(String(50), default="email")
    # messages: list of {role: "agent"|"lead", content: str, timestamp: ISO str}
    messages: Mapped[list] = mapped_column(JSONB, default=list)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # LLM-generated summary of conversation
    # embedding: pgvector column for semantic search — nullable, populated by embedding_service
    # Requires: CREATE EXTENSION IF NOT EXISTS vector; ALTER TABLE conversations ADD COLUMN embedding vector(768);
    # Skipped in SQLAlchemy model definition to keep Postgres extension optional at startup.
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    sentiment: Mapped[str | None] = mapped_column(String(50), nullable=True)   # positive|neutral|frustrated|angry|confused
    needs_human: Mapped[bool] = mapped_column(Boolean, default=False)
    human_flagged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    lead: Mapped["Lead"] = relationship(back_populates="conversations", foreign_keys=[lead_id])


# ---------------------------------------------------------------------------
# Booking
# ---------------------------------------------------------------------------

class BookingRequest(Base):
    """A meeting booking attempt — linked to Cal.com (or Calendly) externally."""
    __tablename__ = "booking_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    lead_id: Mapped[str] = mapped_column(String(36), ForeignKey("leads.id"), index=True)
    # status: pending | link_sent | confirmed | cancelled | rescheduled | no_show
    status: Mapped[str] = mapped_column(String(50), default="pending")
    booking_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_booking_id: Mapped[str | None] = mapped_column(String(255), nullable=True)  # Cal.com / Calendly ID
    meeting_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    pre_call_brief: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    lead: Mapped["Lead"] = relationship(back_populates="booking_requests", foreign_keys=[lead_id])


# ---------------------------------------------------------------------------
# Intent signals
# ---------------------------------------------------------------------------

class IntentSignal(Base):
    """A buyer-intent data point captured for a lead."""
    __tablename__ = "intent_signals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    lead_id: Mapped[str] = mapped_column(String(36), ForeignKey("leads.id"), index=True)
    # signal_type: page_visit | pricing_page | competitor_research | job_posting | funding | news_mention
    signal_type: Mapped[str] = mapped_column(String(100))
    score: Mapped[float] = mapped_column(Float, default=0.0)  # 0.0–1.0 contribution
    # source: heuristic | bombora | g2 | web_scrape
    source: Mapped[str] = mapped_column(String(50), default="heuristic")
    signal_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lead: Mapped["Lead"] = relationship(back_populates="intent_signals", foreign_keys=[lead_id])


# ---------------------------------------------------------------------------
# A/B testing
# ---------------------------------------------------------------------------

class ABTestResult(Base):
    """Aggregate conversion stats for a sequence variant — updated on each outcome."""
    __tablename__ = "ab_test_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    sequence_id: Mapped[str] = mapped_column(String(36), ForeignKey("outreach_sequences.id"), index=True)
    variant: Mapped[str] = mapped_column(String(10))  # "A", "B", etc.
    emails_sent: Mapped[int] = mapped_column(Integer, default=0)
    emails_opened: Mapped[int] = mapped_column(Integer, default=0)
    replies: Mapped[int] = mapped_column(Integer, default=0)
    meetings_booked: Mapped[int] = mapped_column(Integer, default=0)
    conversions: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    sequence: Mapped["OutreachSequence"] = relationship()


# ---------------------------------------------------------------------------
# ICP configuration — singleton row (id = "default")
# ---------------------------------------------------------------------------

class ICPConfig(Base):
    """Ideal Customer Profile — stored as a single editable row."""
    __tablename__ = "icp_config"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default="default")
    # Target lists — None means "any"
    industries: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    seniority_levels: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    excluded_industries: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Employee count range (parsed from enrichment.company_size strings)
    min_employees: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_employees: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_by_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)


# ---------------------------------------------------------------------------
# Lead event sourcing — append-only log of all pipeline + user actions
# ---------------------------------------------------------------------------

class LeadEvent(Base):
    """
    Append-only event log for a lead — the event-sourcing record.

    Every pipeline node, trigger, decay check, and human action appends here.
    Unlike LeadHistory (status-change audit), LeadEvent captures full payloads
    so state can be projected or replayed from scratch.
    """
    __tablename__ = "lead_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    lead_id: Mapped[str] = mapped_column(String(36), ForeignKey("leads.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    # e.g. "pipeline.analyse.complete" | "outreach.scheduled" | "trigger.funding_trigger"
    # | "verdict.set" | "human.flagged" | "decay.computed"
    agent_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    lead: Mapped["Lead"] = relationship(back_populates="events", foreign_keys=[lead_id])


# Self-optimization
# ---------------------------------------------------------------------------

class OptimizationRun(Base):
    """Record of each ICP weight adjustment from the self-optimization loop."""
    __tablename__ = "optimization_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    run_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # old/new ICP weights: {"budget": 0.25, "authority": 0.25, "need": 0.25, "timeline": 0.25}
    old_weights: Mapped[dict] = mapped_column(JSONB, default=dict)
    new_weights: Mapped[dict] = mapped_column(JSONB, default=dict)
    improvement_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
