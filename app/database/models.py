import uuid
from datetime import datetime
from sqlalchemy import String, Float, Boolean, Integer, Text, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
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

    enrichments: Mapped[list["Enrichment"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    verdicts: Mapped[list["Verdict"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    agent_logs: Mapped[list["AgentLog"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    history: Mapped[list["LeadHistory"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    assigned_to: Mapped["User | None"] = relationship(foreign_keys=[assigned_to_id])


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
