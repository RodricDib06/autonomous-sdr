"""
Seed demo data for the agent-era features (ROADMAP phases 6-8).

`seed_demo_data.py` predates the campaign agent, provenance grounding,
backtests, and prospecting, so those pages render empty on a fresh demo
install — which is exactly the surface a demo, a screenshot, or a video
needs to show. This script fills them.

Where the real service is deterministic it is called for real rather than
faked, so what the UI displays is genuinely what the code produces:

  - Backtests   → `backtest.run_backtest` scores a generated historical CSV
  - Approvals   → `provenance.ground_email` matches real claims to real sources
  - Campaigns   → `campaign_metrics.build_snapshot` supplies the plan's inputs

Only the campaign agent's prose (diagnosis + report) is written literally,
because generating it would require a live LLM call; the action list uses
the same pydantic vocabulary the agent is restricted to.

Idempotent: everything is tagged and re-running replaces prior demo rows.

    python scripts/seed_demo_flagship.py
"""

from __future__ import annotations

import random
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.connection import SessionLocal  # noqa: E402
from app.database.models import (  # noqa: E402
    BacktestRun,
    BookingRequest,
    Campaign,
    CampaignActionLog,
    CampaignPlan,
    Enrichment,
    Lead,
    LLMCall,
    Organization,
    OutreachEmail,
    ProspectingRun,
    User,
)
from app.services import provenance  # noqa: E402
from app.services.backtest import run_backtest  # noqa: E402
from app.services.campaign_metrics import build_snapshot  # noqa: E402
from app.utils.time import utcnow  # noqa: E402

DEMO_CAMPAIGN_NAME = "Q3 Mid-Market Meetings (demo)"
DEMO_BACKTEST_FILE = "q2-closed-won-lost-demo.csv"

random.seed(42)


# ---------------------------------------------------------------------------
# Historical CSV — a plausible last-quarter CRM export
# ---------------------------------------------------------------------------

_INDUSTRIES = ["SaaS", "Fintech", "Healthcare", "E-commerce", "Logistics", "Manufacturing"]
_TITLES = [
    ("VP of Sales", 0.72), ("Head of Revenue", 0.68), ("Chief Revenue Officer", 0.80),
    ("Sales Director", 0.55), ("Demand Gen Manager", 0.30), ("SDR Manager", 0.35),
    ("Marketing Coordinator", 0.10), ("Account Executive", 0.22), ("Founder", 0.65),
]
_COMPANIES = [
    "Northwind Logistics", "Cobalt Health", "Arbor Fintech", "Lumen Retail", "Kestrel SaaS",
    "Juniper Freight", "Vantage Medical", "Solstice Commerce", "Redpine Analytics",
    "Harbor Payments", "Pinnacle Manufacturing", "Cirrus Robotics", "Meridian Bank",
    "Tessera Labs", "Quill Software", "Bright Harbor", "Ironwood Supply", "Halcyon Care",
]
_FIRST = ["Dana", "Priya", "Marcus", "Elena", "Tomas", "Aisha", "Liam", "Noor", "Ravi",
          "Sofia", "Jonas", "Mei", "Owen", "Ingrid", "Diego", "Yuki", "Clara", "Samir"]
_LAST = ["Whitfield", "Raman", "Okonkwo", "Vasquez", "Lindqvist", "Haddad", "Byrne",
         "El-Amin", "Patel", "Moreau", "Keller", "Tanaka", "Fitzgerald", "Sorensen"]


def _historical_csv(rows: int = 220) -> str:
    """
    Build a CSV whose real outcomes correlate with the signals the qualifier
    keys on — decision-making seniority and ICP industry fit — but noisily,
    so the calibration report shows genuine misses rather than a perfect
    diagonal. A backtest that scores 1.0 proves nothing except that the
    fixture was rigged.
    """
    # (job_title, industry pool, size pool, true win rate) — tiers deliberately
    # span the scorer's range so every calibration bucket it can reach is used.
    tiers = [
        # Decision makers at ICP-fit companies: the qualifier should call these Hot
        (["Chief Revenue Officer", "VP of Sales", "Founder", "VP of Revenue"],
         ["SaaS", "FinTech", "Software", "Technology"], [80, 120, 180, 250, 400], 0.62, 55),
        # Right title, wrong industry: authority without need
        (["Chief Revenue Officer", "VP of Sales", "Head of Revenue"],
         ["Logistics", "Manufacturing", "Healthcare"], [120, 400, 900], 0.30, 40),
        # Right industry, mid authority: the Warm middle where calibration matters
        (["Sales Director", "Head of Growth", "SDR Manager", "Demand Gen Manager"],
         ["SaaS", "FinTech", "Software"], [45, 80, 150, 300], 0.33, 60),
        # Junior / poor fit: should land Cold and rarely convert
        (["Marketing Coordinator", "Junior Account Executive", "Sales Associate"],
         ["E-commerce", "Logistics", "Healthcare", "Manufacturing"], [15, 40, 90], 0.08, 45),
        # Small ICP-fit companies: fast timeline, thin budget — genuinely ambiguous
        (["Founder", "Head of Sales"], ["SaaS", "DevTools"], [12, 25, 45], 0.38, 20),
    ]

    lines = ["name,email,company,job_title,industry,company_size,revenue,outcome"]
    row_id = 0
    for titles, industries, sizes, win_rate, count in tiers:
        for _ in range(count):
            if row_id >= rows:
                break
            title = random.choice(titles)
            industry = random.choice(industries)
            size = random.choice(sizes)
            company = random.choice(_COMPANIES)
            first, last = random.choice(_FIRST), random.choice(_LAST)
            domain = company.lower().replace(" ", "") + ".com"
            email = f"{first.lower()}.{last.lower()}{row_id}@{domain}"
            outcome = "won" if random.random() < win_rate else "lost"
            revenue = size * random.randint(90_000, 160_000)
            lines.append(
                f"{first} {last},{email},{company},{title},{industry},{size},{revenue},{outcome}"
            )
            row_id += 1

    random.shuffle(lines[1:])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Seeders
# ---------------------------------------------------------------------------

def seed_backtest(db, org_id: str | None, user_id: str | None) -> None:
    """Replay a generated historical CSV through the real scorer."""
    existing = db.query(BacktestRun).filter(BacktestRun.filename == DEMO_BACKTEST_FILE).all()
    for run in existing:
        db.delete(run)
    db.commit()

    run = run_backtest(
        db,
        csv_content=_historical_csv(),
        filename=DEMO_BACKTEST_FILE,
        org_id=org_id,
        created_by_id=user_id,
    )
    s = run.summary or {}
    print(
        f"  backtest: {run.total_rows} rows scored — "
        f"hot_recall={s.get('hot_recall')} hot_precision={s.get('hot_precision')} "
        f"lift={s.get('hot_lift')}"
    )


def _research_for(company: str, industry: str, variant: int) -> dict:
    """
    The evidence the ReAct research agent would have left on the lead. These
    snippets are what the Fact Check panel unfolds as the source behind a
    verified claim, so the email templates below quote them closely — which
    is exactly what a grounded generation does.
    """
    payloads = [
        {
            "headline": f"{company} raises $12M Series B",
            "snippet": (
                f"{company} announced a $12M Series B led by Kestrel Ventures. "
                f"The company said it will grow its revenue team by 40% and expand "
                f"into two new markets over the next year."
            ),
        },
        {
            "headline": f"{company} opens 9 new roles across sales",
            "snippet": (
                f"{company} is hiring for 9 open roles across sales and customer "
                f"success, after reporting that inbound demand in {industry} grew "
                f"faster than its team could cover last quarter."
            ),
        },
        {
            "headline": f"{company} launches self-serve tier",
            "snippet": (
                f"{company} launched a self-serve product tier this quarter, "
                f"which the company expects to triple signup volume and shift more "
                f"qualification work onto its 6-person sales team."
            ),
        },
    ]
    p = payloads[variant % len(payloads)]
    # Same shape the ReAct research agent records: one note per tool call.
    return {
        "research_summary": f"{company} shows recent growth signals.",
        "research_notes": [
            {
                "tool": "search_web",
                "args": {"query": f"{company} funding hiring news"},
                "result": {"results": [{"title": p["headline"], "snippet": p["snippet"]}]},
            },
            {
                "tool": "verify_icp",
                "args": {"company": company, "industry": industry, "size": "120"},
                "result": {"industry_match": True, "size_match": True},
            },
        ],
    }


def _draft_for(lead, company: str, variant: int) -> tuple[str, str]:
    """
    A personalised draft. Each body mixes claims the research supports with
    one claim nothing supports — the invented detail is the whole reason the
    approval queue exists, so the demo has to contain one.
    """
    first = (lead.name or "there").split()[0]
    templates = [
        (
            f"congrats on the {company} Series B",
            f"Hi {first},\n\n"
            f"Congratulations on the $12M Series B led by Kestrel Ventures. "
            f"Teams that raise at that stage usually grow the revenue team by 40% "
            f"within a year, and coverage is the first thing to break.\n\n"
            f"Your 14 SDRs are already working the top of the inbound list, so the "
            f"long tail ages out quietly.\n\n"
            f"Worth a short call to show you what that tail is worth?\n\nDana",
        ),
        (
            f"9 open sales roles at {company}",
            f"Hi {first},\n\n"
            f"I saw {company} is hiring for 9 open roles across sales and customer "
            f"success after inbound demand grew faster than the team could cover "
            f"last quarter.\n\n"
            f"Most teams in that position lose 60% of inbound to slow follow-up "
            f"before the new hires even start.\n\n"
            f"Open to comparing notes?\n\nDana",
        ),
        (
            f"{company}'s self-serve launch and a 6-person sales team",
            f"Hi {first},\n\n"
            f"You launched a self-serve tier this quarter, which the company expects "
            f"to triple signup volume onto a 6-person sales team.\n\n"
            f"We cut response time to under 4 minutes for the 3 companies in your "
            f"space we work with.\n\n"
            f"Worth 15 minutes?\n\nDana",
        ),
    ]
    return templates[variant % len(templates)]


def seed_approval_queue(db, limit: int = 12) -> None:
    """
    Put drafts in the approval queue with real provenance reports. Each draft
    is graded by the live `ground_email` code — nothing here hand-writes a
    verdict, so what the Fact Check panel renders is what the matcher decided.
    """
    # Reset any drafts this script parked previously.
    db.query(OutreachEmail).filter(OutreachEmail.status == "pending_approval").update(
        {"status": "draft"}, synchronize_session=False
    )
    db.commit()

    emails = (
        db.query(OutreachEmail)
        .filter(OutreachEmail.status.in_(["draft", "sent"]))
        .order_by(OutreachEmail.created_at.desc())
        .limit(limit * 4)
        .all()
    )

    seeded = 0
    seen_leads: set[str] = set()
    for email in emails:
        if seeded >= limit:
            break
        if email.lead_id in seen_leads:
            continue
        lead = db.query(Lead).filter(Lead.id == email.lead_id).first()
        if not lead or not lead.company or not lead.name:
            continue
        # Skip fixture rows left by test runs — they read badly in a demo.
        if any(t in f"{lead.company} {lead.name} {lead.email}".lower()
               for t in ("test", "example.com", "demo corp", "foo", "acme")):
            continue
        enrichment = db.query(Enrichment).filter(Enrichment.lead_id == lead.id).first()
        industry = (enrichment.industry if enrichment and enrichment.industry else "B2B")

        research = _research_for(lead.company, industry, seeded)
        subject, body = _draft_for(lead, lead.company, seeded)

        report = provenance.ground_email(
            subject=subject,
            body=body,
            lead=lead,
            enrichment=enrichment,
            research=research,
        )
        if not report.get("claims"):
            continue

        email.subject = subject
        email.body = body
        email.claims = report
        email.status = "pending_approval"
        email.sent_at = None
        email.opened_at = None
        email.replied_at = None
        seeded += 1
        seen_leads.add(email.lead_id)

    db.commit()

    graded = db.query(OutreachEmail).filter(OutreachEmail.status == "pending_approval").all()
    flagged = sum(1 for e in graded if (e.claims or {}).get("unverified", 0) > 0)
    total_claims = sum(len((e.claims or {}).get("claims", [])) for e in graded)
    verified = sum((e.claims or {}).get("verified", 0) for e in graded)
    print(
        f"  approvals: {len(graded)} drafts queued — {verified}/{total_claims} claims "
        f"grounded, {flagged} drafts carry an unverified claim"
    )


def _seed_llm_telemetry(db, campaign: Campaign) -> None:
    """
    Meter the LLM work the pipeline would have done inside the campaign window.

    Cost telemetry is what the ROI panel and the campaign's spend constraint
    both read. The base seeder wrote almost none, leaving "$0 LLM spend" on a
    campaign that has sent hundreds of emails — which undercuts the claim that
    every call is metered.
    """
    db.query(LLMCall).filter(LLMCall.agent_name.like("%(demo)")).delete(
        synchronize_session=False
    )
    db.commit()

    start = campaign.period_start
    window_days = max((min(utcnow(), campaign.period_end) - start).days, 1)
    leads = db.query(Lead.id).limit(200).all()
    if not leads:
        return

    # Groq llama-3.1-70b pricing, the project's default provider.
    agents = [
        ("analysis_agent (demo)", 1400, 320),
        ("validator_agent (demo)", 900, 180),
        ("outreach_agent (demo)", 1100, 420),
        ("research_agent (demo)", 1800, 260),
        ("campaign_agent (demo)", 3200, 700),
    ]
    for i in range(320):
        name, p_tok, c_tok = random.choice(agents)
        prompt_tokens = p_tok + random.randint(-200, 200)
        completion_tokens = c_tok + random.randint(-60, 60)
        cost = (prompt_tokens / 1e6) * 0.59 + (completion_tokens / 1e6) * 0.79
        db.add(LLMCall(
            lead_id=random.choice(leads)[0],
            agent_name=name,
            provider="groq",
            model="llama-3.1-70b-versatile",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=round(cost, 6),
            latency_ms=random.randint(380, 2400),
            success=True,
            created_at=start + timedelta(
                days=random.randint(0, window_days - 1),
                hours=random.randint(8, 18),
                minutes=random.randint(0, 59),
            ),
        ))
    db.commit()


def _seed_conversion_stages(db) -> None:
    """
    Spread leads across the revenue funnel's stages.

    The dashboard funnel counts `conversion_status` against
    ["unqualified", "qualified", "contacted", "scheduled", "won", "lost"].
    The base seeder only ever wrote "unqualified", "converted" (not a stage
    at all), and "lost", so every stage below the top rendered 0 leads and a
    0% win rate — a working feature that looks broken.
    """
    leads = db.query(Lead).filter(Lead.archived == False).all()  # noqa: E712
    random.shuffle(leads)

    # Monotonically narrowing, as a real funnel is.
    plan = [
        ("unqualified", 0.34), ("qualified", 0.26), ("contacted", 0.18),
        ("scheduled", 0.10), ("won", 0.06), ("lost", 0.06),
    ]
    cursor = 0
    for stage, share in plan:
        take = int(len(leads) * share)
        for lead in leads[cursor:cursor + take]:
            lead.conversion_status = stage
        cursor += take
    for lead in leads[cursor:]:
        lead.conversion_status = "unqualified"

    db.commit()


def _normalise_demo_funnel(db) -> None:
    """
    Repair the outreach funnel before dating it into a campaign window.

    Earlier demo runs left a large backlog of `failed` emails (a decommissioned
    model id broke a pipeline run), which makes every rate the campaign page
    computes meaningless. Reshape them into a plausible cold-outreach funnel:
    most delivered, a realistic minority opened/replied, a small bounce tail,
    and a handful genuinely failed — real campaigns are never spotless.
    """
    reusable = (
        db.query(OutreachEmail)
        .filter(OutreachEmail.status.in_(["failed", "sent", "opened", "replied", "bounced"]))
        .all()
    )
    random.shuffle(reusable)

    n = len(reusable)
    n_replied = int(n * 0.055)   # ~5.5% reply rate
    n_opened = int(n * 0.32)     # ~38% open rate once replies are counted in
    n_bounced = int(n * 0.014)   # ~1.4% bounce rate, inside a 3% ceiling
    n_failed = int(n * 0.02)

    cursor = 0
    for e in reusable[cursor:cursor + n_replied]:
        e.status = "replied"
        e.opened_at = e.opened_at or e.created_at
    cursor += n_replied
    # `opened` is a status, not just a timestamp — /outreach/stats counts the
    # status, so setting opened_at alone leaves the open rate reading zero.
    for e in reusable[cursor:cursor + n_opened]:
        e.status = "opened"
        e.opened_at = e.opened_at or e.created_at
    cursor += n_opened
    for e in reusable[cursor:cursor + n_bounced]:
        e.status = "bounced"
        e.opened_at = None
    cursor += n_bounced
    for e in reusable[cursor:cursor + n_failed]:
        e.status = "failed"
        e.opened_at = None
    cursor += n_failed
    for e in reusable[cursor:]:
        e.status = "sent"
        e.opened_at = None

    db.commit()


def _place_activity_in_period(db, campaign: Campaign, target_meetings: int) -> None:
    """
    Move existing demo activity into the campaign window so the page's own
    metrics tell the story the plan describes.

    The campaign card reads confirmed bookings, dispatched sends, and replies
    by timestamp. The base seeder created that activity with no campaign in
    mind, so without this the card reports 0/40 while the agent's diagnosis
    talks about being behind pace — the kind of contradiction a viewer spots
    immediately. Everything is pushed outside the window first, then a
    deliberate slice is dated back inside it.
    """
    start, end = campaign.period_start, campaign.period_end
    before = start - timedelta(days=45)
    window_days = max((min(utcnow(), end) - start).days, 1)

    def _in_window(i: int):
        return start + timedelta(
            days=random.randint(0, window_days - 1),
            hours=random.randint(8, 17),
            minutes=random.randint(0, 59),
        )

    # 1. Bookings — everything out, then exactly `target_meetings` back in.
    bookings = db.query(BookingRequest).all()
    for b in bookings:
        b.created_at = before - timedelta(days=random.randint(0, 20))
    confirmed = [b for b in bookings if b.status == "confirmed"]
    for i, b in enumerate(confirmed[:target_meetings]):
        b.created_at = _in_window(i)

    # 2. Sends and replies — a realistic volume inside the window, leaving the
    #    approval queue (sent_at is NULL there) untouched.
    emails = (
        db.query(OutreachEmail)
        .filter(OutreachEmail.status.in_(["sent", "opened", "replied", "bounced"]))
        .all()
    )
    for e in emails:
        if e.sent_at:
            e.sent_at = before - timedelta(days=random.randint(0, 20))
        if e.replied_at:
            e.replied_at = before - timedelta(days=random.randint(0, 20))

    in_window = emails[: int(len(emails) * 0.65)]
    for i, e in enumerate(in_window):
        sent = _in_window(i)
        e.sent_at = sent
        if e.status == "replied":
            e.replied_at = sent + timedelta(days=random.randint(1, 3))
        if e.opened_at:
            e.opened_at = sent + timedelta(hours=random.randint(1, 30))

    db.commit()


def seed_campaign(db, org_id: str | None, user_id: str | None) -> Campaign:
    """A behind-pace campaign with a plan waiting for human approval."""
    # Delete per-object so the ORM cascade clears plans and action logs;
    # a bulk delete() would trip the campaign_plans foreign key.
    for stale in db.query(Campaign).filter(Campaign.name == DEMO_CAMPAIGN_NAME).all():
        db.query(ProspectingRun).filter(ProspectingRun.campaign_id == stale.id).delete(
            synchronize_session=False
        )
        for plan in stale.plans:
            db.query(CampaignActionLog).filter(
                CampaignActionLog.plan_id == plan.id
            ).delete(synchronize_session=False)
        db.delete(stale)
    db.commit()

    now = utcnow()
    campaign = Campaign(
        org_id=org_id,
        name=DEMO_CAMPAIGN_NAME,
        goal_type="meetings",
        goal_target=20,
        period_start=now - timedelta(days=24),
        period_end=now + timedelta(days=16),
        status="active",
        constraints={
            "max_bounce_rate": 0.03,
            "max_daily_sends": 120,
            "max_monthly_llm_usd": 50.0,
            "segments": [
                {"industry": "SaaS", "company_size_min": 50, "company_size_max": 1000},
                {"industry": "Fintech", "seniority": "vp"},
            ],
        },
        created_by_id=user_id,
        created_at=now - timedelta(days=24),
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    _seed_conversion_stages(db)
    _normalise_demo_funnel(db)
    _place_activity_in_period(db, campaign, target_meetings=10)
    _seed_llm_telemetry(db, campaign)

    # The plan's inputs are the real metrics, and so is the prose below them —
    # a diagnosis quoting numbers the dashboard contradicts is worse than none.
    snapshot = build_snapshot(db, campaign)
    prog, pc = snapshot["progress"], snapshot["pace"]
    total = prog["total"]
    bounce_pct = (total["bounce_rate"] or 0) * 100
    ceiling_pct = (campaign.constraints["max_bounce_rate"]) * 100

    diagnosis = (
        f"Pace is behind: {pc['elapsed_weekdays']} of {pc['total_weekdays']} working "
        f"days in, the campaign has booked {pc['actual']} of {campaign.goal_target} "
        f"meetings against an expected {pc['expected_by_now']} — a pace ratio of "
        f"{pc['pace_ratio']} and a projected finish of {pc['projected_end_total']}. "
        f"The gap is concentrated rather than spread evenly: the Fintech/VP segment "
        f"replies at roughly half the rate of SaaS mid-market on the same sequence, "
        f"and those replies skew toward one objection (\"we already have an SDR "
        f"team\") rather than disinterest. That is an addressable messaging problem, "
        f"not a targeting problem, so this plan keeps the segment and changes the "
        f"message. Deliverability is healthy — bounce rate {bounce_pct:.1f}% against "
        f"the {ceiling_pct:.0f}% ceiling across {total['sends']} sends — and spend is "
        f"${total['spend_usd']:.2f} of the ${campaign.constraints['max_monthly_llm_usd']:.0f} "
        f"monthly ceiling, so there is room to raise volume rather than cut it."
    )

    actions = [
        {
            "action": "pause_sequence",
            "sequence_id": "demo-fintech-v1",
            "reason": "Reply rate 1.9% over 210 sends in the Fintech/VP segment — "
                      "below the 3.5% campaign average with enough volume to call it.",
        },
        {
            "action": "create_variant",
            "based_on_sequence_id": "demo-fintech-v1",
            "angle": "Lead with augmentation, not replacement: position the agent as "
                     "coverage for the 60% of inbound an existing SDR team never "
                     "reaches, answering the 'we already have SDRs' objection in the "
                     "opening line instead of the third email.",
            "draft_steps": [
                {"step": 1, "subject": "the leads your team never gets to",
                 "body": "Most SDR teams work the top of the list and let the rest age out..."},
                {"step": 2, "subject": "re: coverage",
                 "body": "Following up with the specific numbers from your inbound volume..."},
            ],
        },
        {
            "action": "adjust_daily_target",
            "value": 95,
            "reason": "Raise from 70 to recover the 3-meeting pace gap within the "
                      "120/day constraint; bounce rate has headroom.",
        },
        {
            "action": "request_prospecting",
            "segment": {"industry": "SaaS", "company_size_min": 50, "company_size_max": 1000},
            "count": 30,
            "reason": "SaaS mid-market converts best and the segment list is nearly "
                      "exhausted — 30 more keeps the winning segment sending.",
        },
    ]

    plan = CampaignPlan(
        campaign_id=campaign.id,
        version=2,
        status="pending_approval",
        generated_at=now - timedelta(hours=6),
        diagnosis=diagnosis,
        actions=actions,
        metrics_snapshot=snapshot,
        report_md=(
            "## Week 3 report\n\n"
            "**Goal:** 40 meetings by the end of the period. **Booked:** 21. "
            "**Pace:** 0.88x (projected 35).\n\n"
            "### What moved\n"
            "- SaaS mid-market held a 4.6% reply rate across 480 sends and produced "
            "16 of the 21 meetings.\n"
            "- Fintech/VP produced 4 meetings on comparable volume; reply rate 1.9%.\n"
            "- Bounce rate 0.6% against a 3% ceiling; no deliverability risk.\n\n"
            "### What I changed last week\n"
            "- Paused the weakest SaaS variant (v1) after it lost to v3 in the bandit.\n\n"
            "### What I want to change now\n"
            "- Pause the Fintech sequence and replace it with an augmentation-angle "
            "variant answering the objection those replies actually raise.\n"
            "- Raise the daily target to 95 and source 30 more SaaS mid-market leads.\n\n"
            "### Risk\n"
            "Raising volume while a new variant is unproven means a week of noisier "
            "data. The bandit will route most traffic to the proven SaaS sequence "
            "until the variant earns its share."
        ),
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)

    # A previous, executed plan — so the page shows history, not a cold start.
    prior = CampaignPlan(
        campaign_id=campaign.id,
        version=1,
        status="superseded",
        generated_at=now - timedelta(days=7, hours=6),
        diagnosis=(
            "Early in the period and slightly ahead of pace. Two SaaS variants are "
            "running with overlapping performance; v1 trails v3 by 1.8 points of "
            "reply rate over 160 sends each, which is enough separation to stop "
            "splitting traffic."
        ),
        actions=[
            {"action": "pause_sequence", "sequence_id": "demo-saas-v1",
             "reason": "Loses to v3 on reply rate with sufficient sample."},
        ],
        metrics_snapshot=snapshot,
        approved_by_id=user_id,
        approved_at=now - timedelta(days=7, hours=5),
    )
    db.add(prior)
    db.commit()
    db.refresh(prior)

    db.add(CampaignActionLog(
        plan_id=prior.id,
        action_type="pause_sequence",
        payload={"sequence_id": "demo-saas-v1", "reason": "Loses to v3 on reply rate."},
        executed_at=now - timedelta(days=7, hours=5),
        success=True,
    ))
    db.commit()

    print(f"  campaign: '{campaign.name}' — v2 plan pending approval, v1 executed")
    return campaign


def seed_prospecting(db, org_id: str | None, campaign: Campaign, user_id: str | None) -> None:
    """Sourcing runs showing the quality gates rejecting candidates."""
    db.query(ProspectingRun).filter(ProspectingRun.org_id == org_id).delete(
        synchronize_session=False
    )
    db.commit()

    now = utcnow()
    runs = [
        (6, "synthetic", {"industry": "SaaS", "company_size_min": 50, "company_size_max": 1000},
         40, 38, 24, {"suppressed": 3, "duplicate": 6, "undeliverable": 4, "low_score": 1, "budget": 0}),
        (3, "synthetic", {"industry": "Fintech", "seniority": "vp"},
         30, 27, 15, {"suppressed": 2, "duplicate": 5, "undeliverable": 3, "low_score": 2, "budget": 0}),
        (1, "synthetic", {"industry": "SaaS", "company_size_min": 50, "company_size_max": 1000},
         30, 30, 19, {"suppressed": 1, "duplicate": 7, "undeliverable": 2, "low_score": 1, "budget": 0}),
    ]
    for days_ago, provider, criteria, requested, found, accepted, rejected in runs:
        db.add(ProspectingRun(
            org_id=org_id,
            campaign_id=campaign.id,
            provider=provider,
            criteria=criteria,
            requested=requested,
            found=found,
            accepted=accepted,
            rejected=rejected,
            cost_usd=0.0,
            dry_run=False,
            created_by_id=user_id,
            created_at=now - timedelta(days=days_ago),
        ))
    db.commit()
    print(f"  prospecting: {len(runs)} sourcing runs with gate rejection breakdowns")


def main() -> None:
    db = SessionLocal()
    try:
        org = db.query(Organization).first()
        user = db.query(User).first()
        org_id = org.id if org else None
        user_id = user.id if user else None

        print("Seeding flagship demo data (campaigns, approvals, backtests, prospecting)...")
        seed_backtest(db, org_id, user_id)
        seed_approval_queue(db)
        campaign = seed_campaign(db, org_id, user_id)
        seed_prospecting(db, org_id, campaign, user_id)
        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
