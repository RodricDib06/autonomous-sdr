"""
Campaign Manager Agent — goal-directed autonomy.

The loop: observe → diagnose → propose → (approve) → execute → report.

The agent is handed a Campaign (quota + period + constraints) and plans
against it using primitives that already exist: pausing/creating sequences
feeds the Thompson bandit, the daily send target feeds the outreach
scheduler, prospecting tops up the pipeline (Phase 7), and escalation goes
to Slack. Two hard design rules:

  1. The LLM can ONLY emit actions from the pydantic vocabulary below —
     anything else fails validation. Constraint checks happen in code,
     never in the prompt.
  2. The agent must never fail open: a malformed LLM response degrades to
     a conservative plan (escalate + change nothing), not an exception.

Deliberate omission: there is no "reallocate traffic" action. Traffic
allocation is already Thompson sampling's job — seeding it with synthetic
counts would corrupt the measured A/B stats. The agent's levers over
allocation are pausing losers and introducing new variants.

Autonomy: org setting `campaign_autonomy` — "approve" (default; plans wait
for a human) or "auto" (plans execute immediately). Same trust ramp as the
email dial, one level up.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import (
    Campaign,
    CampaignActionLog,
    CampaignPlan,
    OutreachSequence,
)
from app.services import campaign_metrics
from app.services.tenancy import get_org_setting, set_org_setting
from app.utils.time import utcnow

log = logging.getLogger(__name__)

MAX_ACTIONS_PER_PLAN = 6
MAX_VARIANT_STEPS = 5
PACE_DRIFT_REPLAN_THRESHOLD = 0.15
PLAN_MAX_AGE_DAYS = 7

CAMPAIGN_AUTONOMY_MODES = ("approve", "auto")


# ---------------------------------------------------------------------------
# Action vocabulary — the ONLY things the agent can do
# ---------------------------------------------------------------------------

class DraftStep(BaseModel):
    step: int = Field(ge=1, le=MAX_VARIANT_STEPS)
    delay_days: int = Field(ge=0, le=30)
    subject_template: str = Field(min_length=1, max_length=500)
    body_template: str = Field(min_length=1)


class PauseSequence(BaseModel):
    type: Literal["pause_sequence"]
    sequence_id: str
    reason: str


class ResumeSequence(BaseModel):
    type: Literal["resume_sequence"]
    sequence_id: str
    reason: str


class CreateVariant(BaseModel):
    type: Literal["create_variant"]
    angle: str = Field(min_length=1, max_length=200)
    draft_steps: list[DraftStep] = Field(min_length=1, max_length=MAX_VARIANT_STEPS)
    based_on_sequence_id: str | None = None


class AdjustDailyTarget(BaseModel):
    type: Literal["adjust_daily_target"]
    value: int = Field(ge=1)
    reason: str


class RequestProspecting(BaseModel):
    type: Literal["request_prospecting"]
    segment: dict = Field(default_factory=dict)
    count: int = Field(ge=1, le=200)
    reason: str


class Escalate(BaseModel):
    type: Literal["escalate"]
    severity: Literal["info", "warning", "critical"]
    message: str


Action = Annotated[
    Union[PauseSequence, ResumeSequence, CreateVariant, AdjustDailyTarget,
          RequestProspecting, Escalate],
    Field(discriminator="type"),
]


class PlanProposal(BaseModel):
    diagnosis: str = Field(min_length=1)
    actions: list[Action] = Field(default_factory=list, max_length=MAX_ACTIONS_PER_PLAN)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_PLANNER_PROMPT = """You are the campaign manager for an autonomous B2B outbound platform.

Campaign goal: {goal_target} {goal_type} between {period_start} and {period_end}.
Constraints: {constraints_json}

Current state (metrics snapshot):
{snapshot_json}

Outcome of your previous plan (empty if this is the first):
{last_plan_json}

Decide what to change. Available actions (respond with ONLY these types):
  pause_sequence      {{"type": "pause_sequence", "sequence_id": "...", "reason": "..."}}
  resume_sequence     {{"type": "resume_sequence", "sequence_id": "...", "reason": "..."}}
  create_variant      {{"type": "create_variant", "angle": "<one-line messaging angle>",
                        "draft_steps": [{{"step": 1, "delay_days": 0,
                        "subject_template": "...", "body_template": "..."}}],
                        "based_on_sequence_id": null}}
  adjust_daily_target {{"type": "adjust_daily_target", "value": <int>, "reason": "..."}}
  request_prospecting {{"type": "request_prospecting", "segment": {{"industry": "..."}},
                        "count": <int>, "reason": "..."}}
  escalate            {{"type": "escalate", "severity": "info|warning|critical", "message": "..."}}

Guidance:
- If pace_ratio < 0.85 the campaign is behind: diagnose WHY (weak sequences?
  not enough pipeline? bounces?) and act on the cause.
- Pause a sequence only with meaningful volume behind the decision (>= 20 sends).
- New variants must address a specific diagnosed weakness — name it in "angle".
- Templates may use placeholders: {{first_name}}, {{company}}, {{industry}}, {{sender_name}}.
- If nothing needs changing, return an empty actions list and say why.
- At most {max_actions} actions.

Respond with ONLY valid JSON:
{{"diagnosis": "<2-4 sentences on where the campaign stands and why>",
  "actions": [ ... ]}}"""


def _parse_json(raw: str) -> dict:
    text = re.sub(r"```(?:json)?\s*", "", raw or "").strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object in planner response: {text[:200]}")
    return json.loads(match.group())


# ---------------------------------------------------------------------------
# Validation — constraints are enforced HERE, not in the prompt
# ---------------------------------------------------------------------------

def _org_sequence_ids(db: Session, org_id: str | None) -> set[str]:
    q = db.query(OutreachSequence.id)
    if org_id is not None:
        q = q.filter(
            (OutreachSequence.org_id == org_id) | (OutreachSequence.org_id.is_(None))
        )
    return {row[0] for row in q.all()}


def validate_actions(
    db: Session, campaign: Campaign, actions: list[Action]
) -> tuple[list[Action], list[str]]:
    """Drop any action that violates constraints or references foreign objects."""
    constraints = campaign.constraints or {}
    known_sequences = _org_sequence_ids(db, campaign.org_id)

    accepted: list[Action] = []
    rejected: list[str] = []
    for action in actions[:MAX_ACTIONS_PER_PLAN]:
        if isinstance(action, (PauseSequence, ResumeSequence)):
            if action.sequence_id not in known_sequences:
                rejected.append(f"{action.type}: unknown sequence {action.sequence_id[:12]}")
                continue
        if isinstance(action, AdjustDailyTarget):
            max_sends = constraints.get("max_daily_sends")
            if max_sends is not None and action.value > int(max_sends):
                rejected.append(
                    f"adjust_daily_target: {action.value} exceeds constraint max_daily_sends={max_sends}"
                )
                continue
            if action.value > settings.OUTREACH_DAILY_SEND_LIMIT:
                rejected.append(
                    f"adjust_daily_target: {action.value} exceeds global cap "
                    f"{settings.OUTREACH_DAILY_SEND_LIMIT}"
                )
                continue
        accepted.append(action)
    return accepted, rejected


# ---------------------------------------------------------------------------
# Plan generation
# ---------------------------------------------------------------------------

def _fallback_proposal(reason: str) -> PlanProposal:
    """The agent must never fail open — degrade to 'change nothing, tell a human'."""
    return PlanProposal(
        diagnosis=f"Planner could not produce a valid plan ({reason}). "
                  "No changes applied; a human should review.",
        actions=[Escalate(type="escalate", severity="warning",
                          message=f"Campaign planner degraded: {reason}")],
    )


def _last_plan_summary(db: Session, campaign: Campaign) -> dict:
    last = (
        db.query(CampaignPlan)
        .filter(CampaignPlan.campaign_id == campaign.id)
        .order_by(CampaignPlan.version.desc())
        .first()
    )
    if last is None:
        return {}
    executed = (
        db.query(CampaignActionLog)
        .filter(CampaignActionLog.plan_id == last.id)
        .all()
    )
    return {
        "version": last.version,
        "status": last.status,
        "diagnosis": last.diagnosis,
        "pace_ratio_then": ((last.metrics_snapshot or {}).get("pace") or {}).get("pace_ratio"),
        "executed_actions": [
            {"type": a.action_type, "success": a.success} for a in executed
        ],
    }


def generate_plan(db: Session, campaign: Campaign, ai_client=None) -> CampaignPlan:
    """
    One observe→diagnose→propose cycle. Persists and returns the plan;
    in `campaign_autonomy=auto` the caller is expected to execute it.
    """
    snapshot = campaign_metrics.build_snapshot(db, campaign)
    last_plan = _last_plan_summary(db, campaign)

    if ai_client is None:
        from app.services.providers import get_ai_client
        ai_client = get_ai_client()

    prompt = _PLANNER_PROMPT.format(
        goal_target=campaign.goal_target,
        goal_type=campaign.goal_type,
        period_start=campaign.period_start.date().isoformat(),
        period_end=campaign.period_end.date().isoformat(),
        constraints_json=json.dumps(campaign.constraints or {}),
        snapshot_json=json.dumps(snapshot, indent=1)[:6000],
        last_plan_json=json.dumps(last_plan),
        max_actions=MAX_ACTIONS_PER_PLAN,
    )

    try:
        proposal = PlanProposal(**_parse_json(ai_client.generate(prompt)))
    except (ValidationError, ValueError, json.JSONDecodeError) as e:
        log.warning(f"[campaign] planner output invalid for {campaign.id[:8]}: {e}")
        proposal = _fallback_proposal("invalid planner output")
    except Exception as e:
        log.warning(f"[campaign] planner LLM call failed for {campaign.id[:8]}: {e}")
        proposal = _fallback_proposal("LLM unavailable")

    accepted, rejected = validate_actions(db, campaign, proposal.actions)
    diagnosis = proposal.diagnosis
    if rejected:
        diagnosis += "\n\nRejected by constraint validation: " + "; ".join(rejected)

    # Anything still waiting on approval is now stale
    db.query(CampaignPlan).filter(
        CampaignPlan.campaign_id == campaign.id,
        CampaignPlan.status == "pending_approval",
    ).update({"status": "superseded"})

    last_version = (
        db.query(CampaignPlan)
        .filter(CampaignPlan.campaign_id == campaign.id)
        .count()
    )
    plan = CampaignPlan(
        campaign_id=campaign.id,
        version=last_version + 1,
        status="pending_approval",
        diagnosis=diagnosis,
        actions=[a.model_dump() for a in accepted],
        metrics_snapshot=snapshot,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    log.info(
        f"[campaign] plan v{plan.version} for '{campaign.name}' "
        f"({len(accepted)} action(s), {len(rejected)} rejected)"
    )
    return plan


# ---------------------------------------------------------------------------
# Execution — deterministic, logged, idempotent
# ---------------------------------------------------------------------------

def _next_variant_letter(db: Session, org_id: str | None) -> str:
    q = db.query(OutreachSequence.ab_variant)
    if org_id is not None:
        q = q.filter(
            (OutreachSequence.org_id == org_id) | (OutreachSequence.org_id.is_(None))
        )
    used = {v[0] for v in q.all() if v[0]}
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if letter not in used:
            return letter
    return "Z"


def _execute_action(db: Session, campaign: Campaign, action: dict) -> dict:
    """Apply one validated action. Returns a result payload for the log."""
    kind = action.get("type")

    if kind in ("pause_sequence", "resume_sequence"):
        seq = db.query(OutreachSequence).filter(
            OutreachSequence.id == action["sequence_id"]
        ).first()
        if seq is None:
            raise ValueError(f"sequence {action['sequence_id']} not found")
        seq.is_active = kind == "resume_sequence"
        db.commit()
        return {"sequence_id": seq.id, "is_active": seq.is_active}

    if kind == "create_variant":
        variant = _next_variant_letter(db, campaign.org_id)
        seq = OutreachSequence(
            org_id=campaign.org_id,
            name=f"[agent] {action['angle']}"[:255],
            ab_variant=variant,
            steps=[
                {
                    "step": s["step"],
                    "delay_days": s["delay_days"],
                    "subject_template": s["subject_template"],
                    "body_template": s["body_template"],
                }
                for s in action["draft_steps"]
            ],
            is_active=True,
        )
        db.add(seq)
        db.commit()
        db.refresh(seq)
        return {"sequence_id": seq.id, "ab_variant": variant}

    if kind == "adjust_daily_target":
        set_org_setting(db, campaign.org_id, "daily_send_target", int(action["value"]))
        return {"daily_send_target": int(action["value"])}

    if kind == "request_prospecting":
        # Live wiring lands with the prospecting service (ROADMAP Phase 7);
        # keep the action durable in the log either way.
        try:
            from app.services.prospecting.service import run_prospecting
        except ImportError:
            return {"status": "deferred", "note": "prospecting service not installed"}
        run = run_prospecting(
            db,
            criteria=action.get("segment") or {},
            limit=int(action["count"]),
            org_id=campaign.org_id,
            campaign_id=campaign.id,
        )
        return {"prospecting_run_id": run.id, "accepted": run.accepted}

    if kind == "escalate":
        try:
            from app.services.slack_notifier import SlackNotifier
            notifier = SlackNotifier(settings.SLACK_WEBHOOK_URL)
            if notifier.enabled:
                notifier.notify(
                    f":triangular_flag_on_post: *Campaign '{campaign.name}' — "
                    f"{action['severity']}*: {action['message']}"
                )
        except Exception:
            pass
        return {"severity": action["severity"], "message": action["message"]}

    raise ValueError(f"unknown action type '{kind}'")


def execute_plan(db: Session, plan: CampaignPlan) -> dict:
    """
    Execute an approved plan. Idempotent: an already-active/rejected plan is
    a no-op, and each action is logged whether it succeeded or not.
    """
    if plan.status == "active":
        return {"status": "already_executed", "plan_id": plan.id}
    if plan.status != "approved":
        return {"status": "not_approved", "plan_id": plan.id, "plan_status": plan.status}

    campaign = db.query(Campaign).filter(Campaign.id == plan.campaign_id).first()
    succeeded = failed = 0
    for action in plan.actions or []:
        try:
            result = _execute_action(db, campaign, action)
            db.add(CampaignActionLog(
                plan_id=plan.id, action_type=action.get("type", "unknown"),
                payload={"action": action, "result": result}, success=True,
            ))
            succeeded += 1
        except Exception as e:
            db.rollback()
            db.add(CampaignActionLog(
                plan_id=plan.id, action_type=action.get("type", "unknown"),
                payload={"action": action}, success=False, error_message=str(e)[:500],
            ))
            failed += 1
            log.warning(f"[campaign] action {action.get('type')} failed: {e}")

    plan.status = "active"
    db.commit()
    log.info(f"[campaign] plan v{plan.version} executed ({succeeded} ok, {failed} failed)")
    return {"status": "executed", "plan_id": plan.id, "succeeded": succeeded, "failed": failed}


# ---------------------------------------------------------------------------
# Reports — deterministic markdown; LLM adds a narrative when available
# ---------------------------------------------------------------------------

def build_report(db: Session, campaign: Campaign, ai_client=None) -> str:
    """Agent-written progress report, stored on the latest plan."""
    snapshot = campaign_metrics.build_snapshot(db, campaign)
    p = snapshot["pace"]
    t = snapshot["progress"]["total"]

    recent_actions = (
        db.query(CampaignActionLog)
        .join(CampaignPlan, CampaignActionLog.plan_id == CampaignPlan.id)
        .filter(CampaignPlan.campaign_id == campaign.id)
        .order_by(CampaignActionLog.executed_at.desc())
        .limit(15)
        .all()
    )

    lines = [
        f"# Campaign report — {campaign.name}",
        "",
        f"**Goal:** {campaign.goal_target} {campaign.goal_type} by {campaign.period_end.date().isoformat()}",
        f"**Progress:** {p['actual']} done · expected {p['expected_by_now'] or '—'} by now "
        f"(pace ×{p['pace_ratio'] if p['pace_ratio'] is not None else '—'}) · "
        f"projected {p['projected_end_total'] or '—'} at period end",
        "",
        "## Activity this period",
        f"- {t['sends']} emails sent · {t['replies']} replies · {t['bounces']} bounces "
        f"(rate {t['bounce_rate'] if t['bounce_rate'] is not None else '—'})",
        f"- {t['meetings']} meetings confirmed · {t['qualified']} leads qualified Hot/Warm",
        f"- LLM spend ${t['spend_usd']}",
        "",
        "## What I did",
    ]
    if recent_actions:
        for a in recent_actions:
            marker = "✓" if a.success else "✗"
            detail = (a.payload or {}).get("action", {})
            reason = detail.get("reason") or detail.get("angle") or detail.get("message") or ""
            lines.append(f"- {marker} {a.action_type}: {reason}"[:200])
    else:
        lines.append("- No actions executed yet.")

    if ai_client is None:
        try:
            from app.services.providers import get_ai_client
            ai_client = get_ai_client()
        except Exception:
            ai_client = None
    if ai_client is not None:
        try:
            narrative = ai_client.generate(
                "You are a sales campaign manager writing to your team lead. In 3-4 plain "
                "sentences, summarise what this data says about the campaign and what you "
                f"plan next. Data: {json.dumps(snapshot)[:4000]}"
            ).strip()
            if narrative:
                lines += ["", "## Manager's note", narrative[:1500]]
        except Exception:
            pass  # the deterministic report stands on its own

    report = "\n".join(lines)
    latest = (
        db.query(CampaignPlan)
        .filter(CampaignPlan.campaign_id == campaign.id)
        .order_by(CampaignPlan.version.desc())
        .first()
    )
    if latest is not None:
        latest.report_md = report
        db.commit()
    return report


# ---------------------------------------------------------------------------
# Scheduled review — the daily heartbeat
# ---------------------------------------------------------------------------

def should_replan(db: Session, campaign: Campaign, now=None) -> bool:
    """Replan when there's no plan yet, the last one is old, or pace drifted."""
    now = now or utcnow()
    last = (
        db.query(CampaignPlan)
        .filter(CampaignPlan.campaign_id == campaign.id)
        .order_by(CampaignPlan.version.desc())
        .first()
    )
    if last is None:
        return True
    if (now - last.generated_at).days >= PLAN_MAX_AGE_DAYS:
        return True
    then = ((last.metrics_snapshot or {}).get("pace") or {}).get("pace_ratio")
    current = campaign_metrics.pace(db, campaign, now=now).get("pace_ratio")
    if then is not None and current is not None:
        return abs(current - then) > PACE_DRIFT_REPLAN_THRESHOLD
    return False


def run_campaign_reviews(db: Session, now=None) -> dict:
    """
    Daily job: close finished campaigns, replan drifting ones, and execute
    immediately when the org runs campaign autonomy in "auto".
    """
    now = now or utcnow()
    reviewed = planned = executed = completed = 0

    campaigns = db.query(Campaign).filter(Campaign.status == "active").all()
    for campaign in campaigns:
        reviewed += 1
        if campaign.period_end < now:
            campaign.status = "completed"
            db.commit()
            build_report(db, campaign)
            completed += 1
            continue
        if campaign.period_start > now or not should_replan(db, campaign, now=now):
            continue

        plan = generate_plan(db, campaign)
        planned += 1
        mode = get_org_setting(db, campaign.org_id, "campaign_autonomy", "approve")
        if mode == "auto":
            plan.status = "approved"
            plan.approved_at = utcnow()
            db.commit()
            execute_plan(db, plan)
            executed += 1

    return {"reviewed": reviewed, "planned": planned,
            "auto_executed": executed, "completed": completed}
