"""
Demo data seeder — inserts 30 realistic leads with all Phase 3/4 data.

Run AFTER all migrations:
    python scripts/seed_demo_data.py

Idempotent: skips if demo leads already exist (tagged "demo").
Does NOT depend on Ollama, Redis, or any external API.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
import random

from app.database.connection import SessionLocal, create_all_tables
from app.database.models import (
    Lead, Enrichment, Verdict, AgentLog,
    OutreachEmail, OutreachSequence, ABTestResult,
    BookingRequest, Conversation, IntentSignal,
    OptimizationRun,
)

random.seed(42)

# ---------------------------------------------------------------------------
# Persona data
# ---------------------------------------------------------------------------

HOT_PERSONAS = [
    {
        "name": "Sarah Chen", "email": "s.chen@veritas-ai.com", "company": "Veritas AI",
        "source": "linkedin_signal", "job_title": "VP of Engineering", "seniority": "VP",
        "company_size": "150-300", "industry": "Technology", "revenue_estimate": "$20M-$50M",
        "tech_stack": ["Python", "Kubernetes", "AWS", "Terraform"],
        "bant": {"budget": 0.87, "authority": 0.91, "need": 0.88, "timeline": 0.82},
        "reasoning": "Sarah is VP of Engineering at a 200-person AI startup with strong budget signals from Series B funding. She has full procurement authority and expressed urgent timeline needs to modernize their go-to-market stack.",
        "conversion_status": "converted",
    },
    {
        "name": "Marcus Williams", "email": "m.williams@dataflow.io", "company": "DataFlow Systems",
        "source": "event", "job_title": "Chief Revenue Officer", "seniority": "C-Level",
        "company_size": "300-500", "industry": "FinTech", "revenue_estimate": "$50M-$100M",
        "tech_stack": ["Salesforce", "HubSpot", "Tableau", "Snowflake"],
        "bant": {"budget": 0.92, "authority": 0.97, "need": 0.85, "timeline": 0.78},
        "reasoning": "Marcus is CRO with clear budget authority and an active vendor evaluation in Q1. The company recently raised Series C and is scaling their sales team aggressively.",
        "conversion_status": "converted",
    },
    {
        "name": "Priya Kapoor", "email": "priya.k@cloudpeak.dev", "company": "CloudPeak Solutions",
        "source": "website_form", "job_title": "Head of Growth", "seniority": "Director",
        "company_size": "80-150", "industry": "DevTools", "revenue_estimate": "$5M-$20M",
        "tech_stack": ["React", "Node.js", "GCP", "Datadog"],
        "bant": {"budget": 0.79, "authority": 0.83, "need": 0.91, "timeline": 0.86},
        "reasoning": "Priya leads Growth at a DevTools scale-up with a specific need for automated lead qualification as they plan to double their sales headcount. Timeline is Q1 this year.",
        "conversion_status": "converted",
    },
    {
        "name": "James O'Brien", "email": "jobs@meridian-soft.com", "company": "Meridian Software",
        "source": "inbound_email", "job_title": "COO", "seniority": "C-Level",
        "company_size": "200-400", "industry": "SaaS", "revenue_estimate": "$30M-$70M",
        "tech_stack": ["Salesforce", "Marketo", "Python", "Azure"],
        "bant": {"budget": 0.84, "authority": 0.95, "need": 0.82, "timeline": 0.72},
        "reasoning": "James reached out directly citing a failed manual SDR process. As COO he can approve new tools. Budget confirmed via their recent pricing page visits.",
        "conversion_status": "converted",
    },
    {
        "name": "Elena Sorokina", "email": "e.sorokina@nexgen-analytics.com", "company": "NexGen Analytics",
        "source": "linkedin_signal", "job_title": "VP Sales", "seniority": "VP",
        "company_size": "100-200", "industry": "SaaS", "revenue_estimate": "$15M-$40M",
        "tech_stack": ["Salesforce", "Outreach", "SQL", "Looker"],
        "bant": {"budget": 0.81, "authority": 0.88, "need": 0.87, "timeline": 0.76},
        "reasoning": "Elena is VP Sales expanding her team to 3x and needs pipeline automation. LinkedIn activity shows active competitor research. Q1 purchase window confirmed.",
        "conversion_status": "converted",
    },
    {
        "name": "Daniel Kim", "email": "d.kim@stackbridge.io", "company": "StackBridge",
        "source": "event", "job_title": "Director of RevOps", "seniority": "Director",
        "company_size": "120-250", "industry": "Technology", "revenue_estimate": "$12M-$30M",
        "tech_stack": ["HubSpot", "Segment", "dbt", "Redshift"],
        "bant": {"budget": 0.77, "authority": 0.82, "need": 0.90, "timeline": 0.79},
        "reasoning": "Daniel is RevOps Director with full stack access. He shared specific pain points around lead scoring accuracy and has a Q2 tool evaluation underway.",
        "conversion_status": "converted",
    },
    {
        "name": "Amara Osei", "email": "a.osei@finbridge-capital.com", "company": "FinBridge Capital",
        "source": "marketing_ad", "job_title": "Managing Director", "seniority": "C-Level",
        "company_size": "200-500", "industry": "FinTech", "revenue_estimate": "$80M-$150M",
        "tech_stack": ["Bloomberg Terminal", "Python", "AWS", "Salesforce"],
        "bant": {"budget": 0.93, "authority": 0.96, "need": 0.79, "timeline": 0.68},
        "reasoning": "Senior exec at a fintech firm with high budget. Clicked on enterprise pricing page 3x. Actively building out their institutional sales function.",
        "conversion_status": "unqualified",
    },
    {
        "name": "Lena Müller", "email": "l.mueller@agileops.de", "company": "AgileOps GmbH",
        "source": "inbound_email", "job_title": "Chief Technology Officer", "seniority": "C-Level",
        "company_size": "90-180", "industry": "Technology", "revenue_estimate": "$8M-$20M",
        "tech_stack": ["Go", "Kubernetes", "Terraform", "Datadog"],
        "bant": {"budget": 0.76, "authority": 0.94, "need": 0.84, "timeline": 0.81},
        "reasoning": "CTO with technical decision authority and an explicit need to automate their SDR process. Recently posted 3 SDR job listings — a clear buying signal.",
        "conversion_status": "unqualified",
    },
    {
        "name": "Ryan Torres", "email": "ryan@growthlab.io", "company": "GrowthLab",
        "source": "website_form", "job_title": "CEO", "seniority": "C-Level",
        "company_size": "50-100", "industry": "SaaS", "revenue_estimate": "$3M-$10M",
        "tech_stack": ["HubSpot", "Stripe", "React", "Node.js"],
        "bant": {"budget": 0.74, "authority": 0.98, "need": 0.86, "timeline": 0.84},
        "reasoning": "Founder-CEO with absolute purchase authority at a fast-growing SaaS. Described their SDR problem in detail on the intake form. Ready to buy in 30 days.",
        "conversion_status": "unqualified",
    },
    {
        "name": "Yuki Tanaka", "email": "y.tanaka@pixelstorm.jp", "company": "PixelStorm",
        "source": "linkedin_signal", "job_title": "VP Product & Growth", "seniority": "VP",
        "company_size": "100-200", "industry": "Technology", "revenue_estimate": "$10M-$25M",
        "tech_stack": ["TypeScript", "PostgreSQL", "GCP", "Mixpanel"],
        "bant": {"budget": 0.80, "authority": 0.85, "need": 0.89, "timeline": 0.77},
        "reasoning": "VP level with combined product and growth ownership. Company recently shifted to PLG and urgently needs lead intelligence for their sales-assist motion.",
        "conversion_status": "unqualified",
    },
]

WARM_PERSONAS = [
    {
        "name": "Carlos Reyes", "email": "c.reyes@synaptix.com", "company": "Synaptix",
        "source": "marketing_ad", "job_title": "Sales Operations Manager", "seniority": "Manager",
        "company_size": "80-150", "industry": "Software", "revenue_estimate": "$8M-$20M",
        "tech_stack": ["Salesforce", "Outreach", "Clari"],
        "bant": {"budget": 0.55, "authority": 0.58, "need": 0.71, "timeline": 0.44},
        "reasoning": "Mid-level ops role with partial decision authority. Clear need but budget requires sign-off from CFO. Timeline is H2 rather than immediate.",
    },
    {
        "name": "Nina Patel", "email": "nina.patel@streamline-hq.com", "company": "Streamline HQ",
        "source": "website_form", "job_title": "Director of Marketing", "seniority": "Director",
        "company_size": "60-120", "industry": "SaaS", "revenue_estimate": "$5M-$15M",
        "tech_stack": ["HubSpot", "Mailchimp", "Google Analytics"],
        "bant": {"budget": 0.58, "authority": 0.62, "need": 0.74, "timeline": 0.51},
        "reasoning": "Marketing director evaluating tools for Q3. Has influence but not final budget approval. Opened both follow-up emails.",
    },
    {
        "name": "Omar Hassan", "email": "o.hassan@infrastack.io", "company": "InfraStack",
        "source": "event", "job_title": "Engineering Manager", "seniority": "Manager",
        "company_size": "100-200", "industry": "DevTools", "revenue_estimate": "$12M-$30M",
        "tech_stack": ["Go", "AWS", "Terraform", "PagerDuty"],
        "bant": {"budget": 0.52, "authority": 0.65, "need": 0.78, "timeline": 0.42},
        "reasoning": "Technical manager who can champion internally but needs director sign-off. Engaged in conversation thread about pricing tiers.",
    },
    {
        "name": "Sophie Laurent", "email": "s.laurent@techlift-fr.com", "company": "TechLift",
        "source": "inbound_email", "job_title": "Head of Business Development", "seniority": "Manager",
        "company_size": "70-130", "industry": "Technology", "revenue_estimate": "$7M-$18M",
        "tech_stack": ["Pipedrive", "LinkedIn Sales Nav", "Notion"],
        "bant": {"budget": 0.61, "authority": 0.70, "need": 0.69, "timeline": 0.55},
        "reasoning": "BizDev head with decent authority. Budget is constrained but there is willingness to explore. Q3 decision window.",
    },
    {
        "name": "Alex Novak", "email": "a.novak@databridge-eu.com", "company": "DataBridge",
        "source": "linkedin_signal", "job_title": "Revenue Operations Lead", "seniority": "Manager",
        "company_size": "90-180", "industry": "FinTech", "revenue_estimate": "$10M-$25M",
        "tech_stack": ["HubSpot", "dbt", "Stripe", "Snowflake"],
        "bant": {"budget": 0.57, "authority": 0.68, "need": 0.73, "timeline": 0.49},
        "reasoning": "RevOps lead with strong analytical background. Has influence in tool selection but shares authority with VP Sales.",
    },
    {
        "name": "Maria Santos", "email": "m.santos@grovetech.br", "company": "GroveTech",
        "source": "marketing_ad", "job_title": "CMO", "seniority": "C-Level",
        "company_size": "50-100", "industry": "Software", "revenue_estimate": "$4M-$10M",
        "tech_stack": ["Mailchimp", "WordPress", "Stripe"],
        "bant": {"budget": 0.50, "authority": 0.72, "need": 0.67, "timeline": 0.38},
        "reasoning": "CMO at a smaller company with high authority but limited budget for tooling. Need is clear; will revisit in next fiscal quarter.",
    },
    {
        "name": "Tom Bergmann", "email": "t.bergmann@logicflow.de", "company": "LogicFlow",
        "source": "website_form", "job_title": "VP of Customer Success", "seniority": "VP",
        "company_size": "100-200", "industry": "SaaS", "revenue_estimate": "$15M-$35M",
        "tech_stack": ["Salesforce", "Gainsight", "Zendesk"],
        "bant": {"budget": 0.59, "authority": 0.75, "need": 0.72, "timeline": 0.46},
        "reasoning": "CS VP looking to automate their expansion pipeline qualification. Good authority but needs sales team alignment. Mid-year evaluation.",
    },
    {
        "name": "Fatima Al-Rashid", "email": "f.alrashid@meridian-mea.com", "company": "Meridian MEA",
        "source": "event", "job_title": "Sales Director", "seniority": "Director",
        "company_size": "150-300", "industry": "Technology", "revenue_estimate": "$20M-$50M",
        "tech_stack": ["Salesforce", "LinkedIn Sales Nav", "Gong"],
        "bant": {"budget": 0.63, "authority": 0.78, "need": 0.70, "timeline": 0.52},
        "reasoning": "Sales Director with regional budget authority. Expressed interest but current tooling contract expires in 8 months.",
    },
]

COLD_PERSONAS = [
    {
        "name": "Brett Thompson", "email": "b.thompson@oldco.com", "company": "OldCo Corp",
        "source": "website_form", "job_title": "Junior Sales Rep", "seniority": "IC",
        "company_size": "1000+", "industry": "Manufacturing", "revenue_estimate": "$500M+",
        "tech_stack": ["Excel", "Outlook"],
        "bant": {"budget": 0.22, "authority": 0.18, "need": 0.31, "timeline": 0.15},
        "reasoning": "Junior IC with no purchase authority at a large manufacturing company outside ICP. No budget signals and long enterprise procurement cycles.",
    },
    {
        "name": "Jessica Park", "email": "j.park@ngo-impact.org", "company": "Impact NGO",
        "source": "marketing_ad", "job_title": "Programme Coordinator", "seniority": "IC",
        "company_size": "10-50", "industry": "Non-Profit", "revenue_estimate": "<$1M",
        "tech_stack": ["Google Workspace", "Airtable"],
        "bant": {"budget": 0.09, "authority": 0.25, "need": 0.35, "timeline": 0.20},
        "reasoning": "NGO with no budget and outside ICP industry. Engagement appears to be research-focused rather than purchase intent.",
    },
    {
        "name": "Kevin Lau", "email": "kevin.l@startuphub.co", "company": "StartupHub",
        "source": "website_form", "job_title": "Founder", "seniority": "C-Level",
        "company_size": "1-10", "industry": "Technology", "revenue_estimate": "<$500K",
        "tech_stack": ["Notion", "Slack", "Stripe"],
        "bant": {"budget": 0.15, "authority": 0.92, "need": 0.45, "timeline": 0.30},
        "reasoning": "Founder with full authority but pre-revenue startup. Below minimum company size threshold and no budget for tooling at this stage.",
    },
    {
        "name": "Hannah Beck", "email": "h.beck@agency-creative.com", "company": "Creative Agency",
        "source": "inbound_email", "job_title": "Account Manager", "seniority": "IC",
        "company_size": "20-50", "industry": "Marketing", "revenue_estimate": "$1M-$3M",
        "tech_stack": ["Adobe CC", "Figma", "Asana"],
        "bant": {"budget": 0.20, "authority": 0.28, "need": 0.32, "timeline": 0.25},
        "reasoning": "Small creative agency outside ICP vertical and below minimum size. No clear product-market fit for B2B sales automation.",
    },
    {
        "name": "Pierre Dumont", "email": "p.dumont@retail-eu.fr", "company": "RetailEU",
        "source": "linkedin_signal", "job_title": "Store Manager", "seniority": "Manager",
        "company_size": "500-1000", "industry": "Retail", "revenue_estimate": "$50M-$150M",
        "tech_stack": ["SAP", "POS System"],
        "bant": {"budget": 0.24, "authority": 0.21, "need": 0.28, "timeline": 0.18},
        "reasoning": "Retail industry outside ICP. Store manager with no authority over software procurement. Enterprise sales cycle would be 12+ months.",
    },
]

PROCESSING_PERSONAS = [
    {
        "name": "Isaac Mensah", "email": "i.mensah@proptech-hub.com", "company": "PropTech Hub",
        "source": "linkedin_signal",
    },
    {
        "name": "Chiara Romano", "email": "c.romano@cloudnative.it", "company": "CloudNative.it",
        "source": "website_form",
    },
]

PENDING_PERSONAS = [
    {
        "name": "Jack Morrison", "email": "j.morrison@saasco.io", "company": "SaaSCo",
        "source": "marketing_ad",
    },
    {
        "name": "Aisha Kamara", "email": "a.kamara@techrise.africa", "company": "TechRise Africa",
        "source": "event",
    },
]

FAILED_PERSONAS = [
    {
        "name": "Unknown Contact", "email": "noreply@tempmail.xyz", "company": "Unknown",
        "source": "website_form",
    },
    {
        "name": "Test Lead", "email": "test@disposable.com", "company": "Test Corp",
        "source": "marketing_ad",
    },
    {
        "name": "Invalid Data", "email": "bad-email", "company": "",
        "source": "website_form",
    },
]

# LangGraph node names in execution order
CORE_NODES = ["orchestrate", "enrich", "score_intent", "analyse", "validate"]
VERDICT_NODES = {"Hot": "booking", "Warm": "outreach", "Cold": "sync_crm"}

# Realistic outreach subjects
SUBJECTS = [
    "Quick question about {company}",
    "How {industry} teams use us",
    "Re: Quick question about {company}",
    "A resource for {company}",
    "Closing the loop — {company}",
    "Last note — {company}",
]

CONVERSATION_MSGS = [
    ("assistant", "Hi {first_name}, I noticed {company} is scaling its go-to-market motion. Would love to show you how AutonomousSDR can automate your lead qualification. 15 minutes this week?"),
    ("user", "Sure, sounds interesting. What does it actually do?"),
    ("assistant", "Great question! AutonomousSDR uses a multi-agent pipeline to enrich, score, and qualify leads automatically — you only spend time on Hot leads that are genuinely ready to buy. I'll send you a short demo link."),
    ("user", "That looks useful. Can you share pricing?"),
    ("assistant", "Happy to! Our pricing scales with volume. For a team your size at {company}, we typically see ROI within 60 days. Want to hop on a call to walk through it together?"),
]

INTENT_SIGNAL_TYPES = [
    ("linkedin_signal", 0.20, "heuristic"),
    ("seniority_vp_plus", 0.15, "heuristic"),
    ("icp_industry_match", 0.15, "heuristic"),
    ("company_size_match", 0.10, "heuristic"),
    ("recent_funding", 0.20, "crunchbase"),
    ("hot_budget_score", 0.12, "heuristic"),
    ("tight_timeline", 0.08, "heuristic"),
    ("high_need_score", 0.12, "heuristic"),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ago(days=0, hours=0, minutes=0) -> datetime:
    return datetime.utcnow() - timedelta(days=days, hours=hours, minutes=minutes)


def _make_agent_logs(db, lead_id: str, verdict: str, days_ago: int):
    nodes = CORE_NODES + [VERDICT_NODES.get(verdict, "sync_crm")]
    t = _ago(days=days_ago, hours=2)
    for i, name in enumerate(nodes):
        t = t + timedelta(seconds=random.randint(800, 4000))
        log = AgentLog(
            lead_id=lead_id,
            agent_name=name,
            duration_ms=random.randint(300, 4500),
            success=True,
            input_data={"lead_id": lead_id},
            output_data={"status": "ok", "node": name},
            created_at=t,
        )
        db.add(log)


def _make_intent_signals(db, lead_id: str, verdict: str, days_ago: int):
    n_signals = {"Hot": 6, "Warm": 3, "Cold": 1}[verdict]
    signals_pool = INTENT_SIGNAL_TYPES[:n_signals]
    for sig_type, score, source in signals_pool:
        db.add(IntentSignal(
            lead_id=lead_id,
            signal_type=sig_type,
            score=score * random.uniform(0.85, 1.0),
            source=source,
            signal_metadata={"triggered": True},
            captured_at=_ago(days=days_ago),
        ))


def _make_outreach(db, lead_id: str, seq_id: str, verdict: str, days_ago: int):
    if verdict == "Cold":
        return

    statuses_by_verdict = {
        "Hot":  [("sent", "opened", "replied"), ("sent", "opened", None), ("scheduled", None, None)],
        "Warm": [("sent", "opened", None), ("sent", None, None), ("scheduled", None, None)],
    }
    steps = statuses_by_verdict[verdict]

    for step_num, (status, opened, replied) in enumerate(steps, 1):
        sent_at = _ago(days=days_ago - step_num * 3) if status in ("sent", "opened", "replied") else None
        opened_at = _ago(days=days_ago - step_num * 3, hours=2) if opened else None
        replied_at = _ago(days=days_ago - step_num * 3, hours=4) if replied else None
        db.add(OutreachEmail(
            lead_id=lead_id,
            sequence_id=seq_id,
            step_number=step_num,
            subject=SUBJECTS[step_num - 1].format(company="[company]"),
            body=f"Demo email body — step {step_num}.",
            status=status if not replied else "replied",
            scheduled_at=_ago(days=days_ago - step_num * 3 + 1),
            sent_at=sent_at,
            opened_at=opened_at,
            replied_at=replied_at,
        ))


def _make_booking(db, lead_id: str, days_ago: int):
    db.add(BookingRequest(
        lead_id=lead_id,
        status="confirmed",
        booking_link="https://cal.com/autonomoussdr/30min",
        notes="Discovery call booked via outreach sequence.",
        start_time=_ago(days=days_ago - 7),
        end_time=_ago(days=days_ago - 7, hours=-1),
        created_at=_ago(days=days_ago),
    ))


def _make_conversation(db, lead_id: str, first_name: str, company: str, days_ago: int):
    messages = []
    t = _ago(days=days_ago)
    for role, template in CONVERSATION_MSGS[:4]:
        t += timedelta(hours=random.randint(1, 8))
        messages.append({
            "role": role,
            "content": template.format(first_name=first_name, company=company),
            "timestamp": t.isoformat(),
            "channel": "email",
        })
    db.add(Conversation(
        lead_id=lead_id,
        channel="email",
        messages=messages,
        summary=f"Engaged prospect at {company}. Interest confirmed; pricing discussed. Next step: demo call.",
        created_at=_ago(days=days_ago),
        updated_at=t,
    ))


# ---------------------------------------------------------------------------
# Main seeder
# ---------------------------------------------------------------------------

def seed(db):
    # Check idempotency
    existing = db.query(Lead).filter(Lead.tags.contains(["demo"])).count()
    if existing > 0:
        print(f"  ✓ Demo data already present ({existing} leads) — skipping.")
        return

    # ── Outreach sequences ───────────────────────────────────────────────────
    print("  Creating outreach sequences…")
    seq_a = OutreachSequence(name="Standard 3-Step (Variant A)", ab_variant="A", is_active=True, steps=[])
    seq_b = OutreachSequence(name="Value-led 3-Step (Variant B)", ab_variant="B", is_active=True, steps=[])
    db.add(seq_a)
    db.add(seq_b)
    db.flush()

    # A/B test results
    db.add(ABTestResult(sequence_id=seq_a.id, variant="A", emails_sent=48, emails_opened=19, replies=7, meetings_booked=4, conversions=4))
    db.add(ABTestResult(sequence_id=seq_b.id, variant="B", emails_sent=47, emails_opened=16, replies=5, meetings_booked=2, conversions=2))

    # ── Optimization run ────────────────────────────────────────────────────
    print("  Creating optimization run…")
    old_w = {"budget": 0.25, "authority": 0.25, "need": 0.25, "timeline": 0.25}
    new_w = {"budget": 0.21, "authority": 0.33, "need": 0.29, "timeline": 0.17}
    db.add(OptimizationRun(
        run_at=_ago(days=3),
        old_weights=old_w,
        new_weights=new_w,
        improvement_score=0.07,
        sample_size=23,
        notes="Authority and need scores are stronger predictors of conversion than budget in this cohort.",
    ))
    db.add(OptimizationRun(
        run_at=_ago(days=10),
        old_weights={"budget": 0.25, "authority": 0.25, "need": 0.25, "timeline": 0.25},
        new_weights=old_w,
        improvement_score=0.03,
        sample_size=11,
        notes="First optimization run — insufficient sample size; small adjustment applied.",
    ))

    # ── Hot leads ────────────────────────────────────────────────────────────
    print("  Seeding Hot leads…")
    for i, p in enumerate(HOT_PERSONAS):
        days_ago = random.randint(5, 25)
        seq_id = seq_a.id if i % 2 == 0 else seq_b.id
        lead = Lead(
            name=p["name"], email=p["email"], company=p["company"], source=p["source"],
            status="complete", tags=["demo"], archived=False,
            data_quality_score=round(random.uniform(0.78, 0.96), 2),
            completeness_score=round(random.uniform(0.82, 0.98), 2),
            conversion_status=p.get("conversion_status", "unqualified"),
            created_at=_ago(days=days_ago), updated_at=_ago(days=days_ago - 1),
        )
        db.add(lead)
        db.flush()

        enr = Enrichment(
            lead_id=lead.id, job_title=p["job_title"], seniority=p["seniority"],
            company_size=p["company_size"], industry=p["industry"],
            revenue_estimate=p["revenue_estimate"], tech_stack=p["tech_stack"],
            confidence=round(random.uniform(0.80, 0.95), 2), enrichment_source="synthetic",
        )
        db.add(enr)
        db.flush()

        v = Verdict(
            lead_id=lead.id, enrichment_id=enr.id,
            analysis_verdict="Hot", final_verdict="Hot",
            bant_scores=p["bant"],
            confidence_score=round(sum(p["bant"].values()) / 4, 2),
            icp_match=True, validated=True,
            analysis_reasoning=p["reasoning"],
            consistency_notes="All BANT dimensions consistent. No conflicting signals detected.",
        )
        db.add(v)

        _make_agent_logs(db, lead.id, "Hot", days_ago)
        _make_intent_signals(db, lead.id, "Hot", days_ago)
        _make_outreach(db, lead.id, seq_id, "Hot", days_ago)
        _make_booking(db, lead.id, days_ago)
        first_name = p["name"].split()[0]
        _make_conversation(db, lead.id, first_name, p["company"], days_ago)
        print(f"    + Hot: {p['name']} @ {p['company']}")

    # ── Warm leads ───────────────────────────────────────────────────────────
    print("  Seeding Warm leads…")
    for i, p in enumerate(WARM_PERSONAS):
        days_ago = random.randint(3, 18)
        seq_id = seq_a.id if i % 2 == 0 else seq_b.id
        lead = Lead(
            name=p["name"], email=p["email"], company=p["company"], source=p["source"],
            status="complete", tags=["demo"], archived=False,
            data_quality_score=round(random.uniform(0.62, 0.82), 2),
            completeness_score=round(random.uniform(0.70, 0.88), 2),
            conversion_status="unqualified",
            created_at=_ago(days=days_ago), updated_at=_ago(days=days_ago - 1),
        )
        db.add(lead)
        db.flush()

        enr = Enrichment(
            lead_id=lead.id, job_title=p["job_title"], seniority=p["seniority"],
            company_size=p["company_size"], industry=p["industry"],
            revenue_estimate=p["revenue_estimate"], tech_stack=p["tech_stack"],
            confidence=round(random.uniform(0.65, 0.85), 2), enrichment_source="synthetic",
        )
        db.add(enr)
        db.flush()

        v = Verdict(
            lead_id=lead.id, enrichment_id=enr.id,
            analysis_verdict="Warm", final_verdict="Warm",
            bant_scores=p["bant"],
            confidence_score=round(sum(p["bant"].values()) / 4, 2),
            icp_match=True, validated=True,
            analysis_reasoning=p["reasoning"],
            consistency_notes="Moderate BANT alignment. Recommend nurture sequence.",
        )
        db.add(v)

        _make_agent_logs(db, lead.id, "Warm", days_ago)
        _make_intent_signals(db, lead.id, "Warm", days_ago)
        _make_outreach(db, lead.id, seq_id, "Warm", days_ago)
        print(f"    + Warm: {p['name']} @ {p['company']}")

    # ── Cold leads ───────────────────────────────────────────────────────────
    print("  Seeding Cold leads…")
    for p in COLD_PERSONAS:
        days_ago = random.randint(2, 14)
        lead = Lead(
            name=p["name"], email=p["email"], company=p["company"], source=p["source"],
            status="complete", tags=["demo"], archived=False,
            data_quality_score=round(random.uniform(0.40, 0.65), 2),
            completeness_score=round(random.uniform(0.50, 0.72), 2),
            conversion_status="lost",
            created_at=_ago(days=days_ago), updated_at=_ago(days=days_ago - 1),
        )
        db.add(lead)
        db.flush()

        enr = Enrichment(
            lead_id=lead.id, job_title=p["job_title"], seniority=p["seniority"],
            company_size=p["company_size"], industry=p["industry"],
            revenue_estimate=p["revenue_estimate"], tech_stack=p.get("tech_stack", []),
            confidence=round(random.uniform(0.40, 0.65), 2), enrichment_source="synthetic",
        )
        db.add(enr)
        db.flush()

        v = Verdict(
            lead_id=lead.id, enrichment_id=enr.id,
            analysis_verdict="Cold", final_verdict="Cold",
            bant_scores=p["bant"],
            confidence_score=round(sum(p["bant"].values()) / 4, 2),
            icp_match=False, validated=True,
            analysis_reasoning=p["reasoning"],
            consistency_notes="Lead outside ICP. Routed to CRM for archival.",
        )
        db.add(v)

        _make_agent_logs(db, lead.id, "Cold", days_ago)
        _make_intent_signals(db, lead.id, "Cold", days_ago)
        print(f"    + Cold: {p['name']} @ {p['company']}")

    # ── In-flight leads ──────────────────────────────────────────────────────
    print("  Seeding in-flight leads…")
    for p in PROCESSING_PERSONAS:
        db.add(Lead(
            name=p["name"], email=p["email"], company=p["company"], source=p["source"],
            status="processing", tags=["demo"], archived=False,
            created_at=_ago(minutes=random.randint(5, 45)),
        ))
    for p in PENDING_PERSONAS:
        db.add(Lead(
            name=p["name"], email=p["email"], company=p["company"], source=p["source"],
            status="pending", tags=["demo"], archived=False,
            created_at=_ago(minutes=random.randint(1, 15)),
        ))
    for p in FAILED_PERSONAS:
        db.add(Lead(
            name=p["name"], email=p["email"], company=p["company"], source=p["source"],
            status="failed", tags=["demo"], archived=False,
            created_at=_ago(days=random.randint(1, 5)),
        ))

    db.commit()
    total = len(HOT_PERSONAS) + len(WARM_PERSONAS) + len(COLD_PERSONAS) + len(PROCESSING_PERSONAS) + len(PENDING_PERSONAS) + len(FAILED_PERSONAS)
    print(f"\n  ✓ Seeded {total} leads ({len(HOT_PERSONAS)} Hot, {len(WARM_PERSONAS)} Warm, {len(COLD_PERSONAS)} Cold, {len(PROCESSING_PERSONAS) + len(PENDING_PERSONAS)} in-flight, {len(FAILED_PERSONAS)} failed)")
    print("  ✓ 2 outreach sequences with A/B test results")
    print("  ✓ 2 optimization runs with BANT weight history")


if __name__ == "__main__":
    print("AutonomousSDR — Demo Data Seeder")
    create_all_tables()
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()
    print("Done.")
