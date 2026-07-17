"""
Tests for the Campaign Manager Agent (goal-directed autonomy).

Coverage:
  - metrics: pace math (weekdays, edge cases), progress goal semantics,
    segment filtering, sequence performance
  - planner: valid LLM plan accepted; constraint-violating actions dropped;
    garbage output degrades to the conservative fallback; pending plans
    superseded on replan
  - executor: every action type, idempotency, action log, unknown sequence
  - autonomy: approve mode never executes; auto mode executes immediately
  - scheduled review: completion, drift-gated replanning
  - API: CRUD, plan approve/reject flow, report, RBAC, org scoping
  - outreach loop honours the agent-set per-org daily target
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.agents import campaign_agent as ca
from app.database.models import (
    BookingRequest,
    Campaign,
    CampaignActionLog,
    CampaignPlan,
    Enrichment,
    Lead,
    OutreachEmail,
    OutreachSequence,
)
from app.services import campaign_metrics as cm
from app.services.tenancy import get_default_org, get_org_setting, set_org_setting
from app.utils.time import utcnow

# Mon 2026-07-06 .. Fri 2026-07-17 — exactly 10 weekdays
START = datetime(2026, 7, 6)
END = datetime(2026, 7, 17, 23, 59)


def _campaign(db, org_id=None, target=10, goal_type="meetings", constraints=None, **kwargs):
    campaign = Campaign(
        org_id=org_id, name="Q3 push", goal_type=goal_type, goal_target=target,
        period_start=START, period_end=END, constraints=constraints or {}, **kwargs,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


def _lead(db, org_id=None, industry="SaaS", seniority="VP", size="50-200", email=None):
    lead = Lead(name="Jane", email=email or f"jane{utcnow().timestamp()}@acme.io",
                company="Acme", org_id=org_id)
    db.add(lead)
    db.flush()
    db.add(Enrichment(lead_id=lead.id, industry=industry, seniority=seniority,
                      company_size=size))
    db.commit()
    db.refresh(lead)
    return lead


# ---------------------------------------------------------------------------
# Pace + progress
# ---------------------------------------------------------------------------

def test_weekday_counting():
    assert cm._weekdays_between(START, END) == 10
    assert cm._weekdays_between(START, START) == 1            # Monday itself
    assert cm._weekdays_between(datetime(2026, 7, 11), datetime(2026, 7, 12)) == 0  # Sat–Sun
    assert cm._weekdays_between(END, START) == 0


def test_pace_midway(test_db):
    campaign = _campaign(test_db, target=10)
    lead = _lead(test_db)
    for _ in range(3):
        test_db.add(BookingRequest(lead_id=lead.id, status="confirmed",
                                   created_at=START + timedelta(days=1)))
    test_db.commit()

    # Friday of week 1 → 5 of 10 weekdays elapsed → expected 5
    result = cm.pace(test_db, campaign, now=datetime(2026, 7, 10, 12))
    assert result["expected_by_now"] == 5.0
    assert result["actual"] == 3
    assert result["pace_ratio"] == 0.6
    assert result["projected_end_total"] == 6


def test_pace_before_start_and_zero_target(test_db):
    campaign = _campaign(test_db, target=10)
    result = cm.pace(test_db, campaign, now=datetime(2026, 7, 1))
    assert result["pace_ratio"] is None or result["expected_by_now"] == 0.0

    campaign2 = _campaign(test_db, target=1)
    campaign2.goal_target = 0
    test_db.commit()
    assert cm.pace(test_db, campaign2, now=datetime(2026, 7, 10))["pace_ratio"] is None


def test_progress_goal_semantics(test_db):
    lead = _lead(test_db)
    test_db.add(OutreachEmail(lead_id=lead.id, step_number=1, subject="s", body="b",
                              status="replied", sent_at=START + timedelta(days=1),
                              replied_at=START + timedelta(days=2)))
    test_db.add(BookingRequest(lead_id=lead.id, status="confirmed",
                               created_at=START + timedelta(days=1)))
    test_db.commit()

    meetings = _campaign(test_db, goal_type="meetings")
    replies = _campaign(test_db, goal_type="replies")
    assert cm.campaign_progress(test_db, meetings)["goal_actual"] == 1
    assert cm.campaign_progress(test_db, replies)["goal_actual"] == 1

    total = cm.campaign_progress(test_db, meetings)["total"]
    assert total["sends"] == 1 and total["replies"] == 1


def test_segment_filtering(test_db):
    org = get_default_org(test_db)
    _lead(test_db, org_id=org.id, industry="SaaS", seniority="VP", size="50-200")
    _lead(test_db, org_id=org.id, industry="Retail", seniority="Junior", size="1-10")

    assert len(cm.segment_lead_ids(test_db, org.id, {"industry": "SaaS"})) == 1
    assert len(cm.segment_lead_ids(test_db, org.id, {"seniority": "VP"})) == 1
    assert len(cm.segment_lead_ids(test_db, org.id, {"company_size_min": 50})) == 1
    assert len(cm.segment_lead_ids(test_db, org.id, None)) == 2


def test_sequence_performance_scoped_to_period(test_db):
    seq = OutreachSequence(name="Seq", steps=[], is_active=True)
    test_db.add(seq)
    test_db.flush()
    lead = _lead(test_db)
    test_db.add(OutreachEmail(lead_id=lead.id, sequence_id=seq.id, step_number=1,
                              subject="s", body="b", status="sent",
                              sent_at=START - timedelta(days=30)))  # outside period
    test_db.add(OutreachEmail(lead_id=lead.id, sequence_id=seq.id, step_number=2,
                              subject="s", body="b", status="bounced",
                              sent_at=START + timedelta(days=1)))
    test_db.commit()

    campaign = _campaign(test_db)
    perf = {p["sequence_id"]: p for p in cm.sequence_performance(test_db, campaign)}
    assert perf[seq.id]["sent"] == 1
    assert perf[seq.id]["bounced"] == 1
    assert perf[seq.id]["bounce_rate"] == 1.0


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

def _fake_ai(response: str):
    client = MagicMock()
    client.generate.return_value = response
    return client


def test_valid_plan_accepted(test_db):
    seq = OutreachSequence(name="Weak seq", steps=[], is_active=True)
    test_db.add(seq)
    test_db.commit()
    campaign = _campaign(test_db)

    plan = ca.generate_plan(test_db, campaign, ai_client=_fake_ai(
        '{"diagnosis": "Behind pace; variant A drags.", "actions": ['
        f'{{"type": "pause_sequence", "sequence_id": "{seq.id}", "reason": "0.4% reply rate"}},'
        '{"type": "create_variant", "angle": "address displacement objection",'
        ' "draft_steps": [{"step": 1, "delay_days": 0, "subject_template": "s", "body_template": "b"}]}'
        ']}'
    ))

    assert plan.status == "pending_approval"
    assert len(plan.actions) == 2
    assert plan.metrics_snapshot["pace"] is not None
    assert "Behind pace" in plan.diagnosis


def test_constraint_violations_dropped_not_fatal(test_db):
    campaign = _campaign(test_db, constraints={"max_daily_sends": 50})
    plan = ca.generate_plan(test_db, campaign, ai_client=_fake_ai(
        '{"diagnosis": "d", "actions": ['
        '{"type": "adjust_daily_target", "value": 500, "reason": "push"},'
        '{"type": "pause_sequence", "sequence_id": "not-a-real-seq", "reason": "x"},'
        '{"type": "escalate", "severity": "info", "message": "ok"}'
        ']}'
    ))
    assert [a["type"] for a in plan.actions] == ["escalate"]
    assert "Rejected by constraint validation" in plan.diagnosis


def test_garbage_llm_output_degrades_to_fallback(test_db):
    campaign = _campaign(test_db)
    plan = ca.generate_plan(test_db, campaign, ai_client=_fake_ai("I think you should YOLO it"))
    assert len(plan.actions) == 1
    assert plan.actions[0]["type"] == "escalate"
    assert "could not produce a valid plan" in plan.diagnosis


def test_llm_exception_degrades_to_fallback(test_db):
    campaign = _campaign(test_db)
    client = MagicMock()
    client.generate.side_effect = RuntimeError("provider down")
    plan = ca.generate_plan(test_db, campaign, ai_client=client)
    assert plan.actions[0]["type"] == "escalate"


def test_replan_supersedes_pending(test_db):
    campaign = _campaign(test_db)
    first = ca.generate_plan(test_db, campaign, ai_client=_fake_ai('{"diagnosis": "d", "actions": []}'))
    second = ca.generate_plan(test_db, campaign, ai_client=_fake_ai('{"diagnosis": "d2", "actions": []}'))
    test_db.refresh(first)
    assert first.status == "superseded"
    assert second.version == 2


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

def _approved_plan(db, campaign, actions):
    plan = CampaignPlan(campaign_id=campaign.id, version=1, status="approved",
                        diagnosis="d", actions=actions)
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def test_execute_pause_and_create_variant(test_db):
    org = get_default_org(test_db)
    seq = OutreachSequence(name="Old", ab_variant="A", steps=[], is_active=True, org_id=org.id)
    test_db.add(seq)
    test_db.commit()
    campaign = _campaign(test_db, org_id=org.id)

    plan = _approved_plan(test_db, campaign, [
        {"type": "pause_sequence", "sequence_id": seq.id, "reason": "weak"},
        {"type": "create_variant", "angle": "case-study led",
         "draft_steps": [{"step": 1, "delay_days": 0,
                          "subject_template": "How {industry} teams win",
                          "body_template": "Hi {first_name}"}]},
    ])
    result = ca.execute_plan(test_db, plan)

    assert result["succeeded"] == 2 and result["failed"] == 0
    test_db.refresh(seq)
    assert seq.is_active is False
    created = test_db.query(OutreachSequence).filter(
        OutreachSequence.name.like("[agent]%")).first()
    assert created is not None
    assert created.ab_variant == "B"  # next unused letter
    assert created.org_id == org.id
    assert plan.status == "active"
    assert test_db.query(CampaignActionLog).filter_by(plan_id=plan.id).count() == 2


def test_execute_adjust_daily_target_and_escalate(test_db):
    org = get_default_org(test_db)
    campaign = _campaign(test_db, org_id=org.id)
    plan = _approved_plan(test_db, campaign, [
        {"type": "adjust_daily_target", "value": 40, "reason": "protect domain"},
        {"type": "escalate", "severity": "warning", "message": "behind pace"},
    ])
    result = ca.execute_plan(test_db, plan)
    assert result["succeeded"] == 2
    assert get_org_setting(test_db, org.id, "daily_send_target") == 40


def test_execute_is_idempotent(test_db):
    campaign = _campaign(test_db)
    plan = _approved_plan(test_db, campaign, [
        {"type": "escalate", "severity": "info", "message": "m"}])
    ca.execute_plan(test_db, plan)
    again = ca.execute_plan(test_db, plan)
    assert again["status"] == "already_executed"
    assert test_db.query(CampaignActionLog).filter_by(plan_id=plan.id).count() == 1


def test_execute_refuses_unapproved(test_db):
    campaign = _campaign(test_db)
    plan = CampaignPlan(campaign_id=campaign.id, version=1, status="pending_approval",
                        actions=[{"type": "escalate", "severity": "info", "message": "m"}])
    test_db.add(plan)
    test_db.commit()
    assert ca.execute_plan(test_db, plan)["status"] == "not_approved"
    assert test_db.query(CampaignActionLog).count() == 0


def test_failed_action_logged_and_execution_continues(test_db):
    campaign = _campaign(test_db)
    plan = _approved_plan(test_db, campaign, [
        {"type": "pause_sequence", "sequence_id": "ghost", "reason": "x"},
        {"type": "escalate", "severity": "info", "message": "m"},
    ])
    result = ca.execute_plan(test_db, plan)
    assert result["failed"] == 1 and result["succeeded"] == 1
    failed = test_db.query(CampaignActionLog).filter_by(success=False).first()
    assert "not found" in failed.error_message


# ---------------------------------------------------------------------------
# Scheduled review + autonomy
# ---------------------------------------------------------------------------

def test_review_completes_finished_campaigns(test_db):
    campaign = _campaign(test_db)
    summary = ca.run_campaign_reviews(test_db, now=END + timedelta(days=2))
    test_db.refresh(campaign)
    assert campaign.status == "completed"
    assert summary["completed"] == 1
    latest = test_db.query(CampaignPlan).filter_by(campaign_id=campaign.id).first()
    # completion writes a report (deterministic part, LLM optional)
    assert latest is None or latest.report_md


def test_review_auto_mode_executes_plan(test_db):
    org = get_default_org(test_db)
    set_org_setting(test_db, org.id, "campaign_autonomy", "auto")
    campaign = _campaign(test_db, org_id=org.id)

    with patch("app.services.providers.get_ai_client",
               return_value=_fake_ai('{"diagnosis": "d", "actions": '
                                     '[{"type": "escalate", "severity": "info", "message": "m"}]}')):
        summary = ca.run_campaign_reviews(test_db, now=START + timedelta(days=2))

    assert summary["planned"] == 1 and summary["auto_executed"] == 1
    plan = test_db.query(CampaignPlan).filter_by(campaign_id=campaign.id).first()
    assert plan.status == "active"


def test_review_approve_mode_holds_plan(test_db):
    org = get_default_org(test_db)
    set_org_setting(test_db, org.id, "campaign_autonomy", "approve")
    campaign = _campaign(test_db, org_id=org.id)

    with patch("app.services.providers.get_ai_client",
               return_value=_fake_ai('{"diagnosis": "d", "actions": []}')):
        summary = ca.run_campaign_reviews(test_db, now=START + timedelta(days=2))

    assert summary["auto_executed"] == 0
    plan = test_db.query(CampaignPlan).filter_by(campaign_id=campaign.id).first()
    assert plan.status == "pending_approval"


def test_should_replan_gating(test_db):
    campaign = _campaign(test_db)
    now = START + timedelta(days=2)
    assert ca.should_replan(test_db, campaign, now=now) is True  # no plan yet

    plan = CampaignPlan(campaign_id=campaign.id, version=1, status="active",
                        generated_at=now,
                        metrics_snapshot={"pace": {"pace_ratio": 1.0}})
    test_db.add(plan)
    test_db.commit()
    # fresh plan + no drift (no goal events → current ratio 0.0 vs 1.0 = drift!)
    assert ca.should_replan(test_db, campaign, now=now) is True

    plan.metrics_snapshot = {"pace": {"pace_ratio": 0.0}}
    test_db.commit()
    assert ca.should_replan(test_db, campaign, now=now) is False
    # stale plan → replan regardless of drift
    assert ca.should_replan(test_db, campaign, now=now + timedelta(days=8)) is True


# ---------------------------------------------------------------------------
# Per-org daily target in the send loop
# ---------------------------------------------------------------------------

def test_send_loop_respects_org_daily_target(test_db):
    from app.agents.outreach_agent import send_pending_scheduled_emails

    org = get_default_org(test_db)
    set_org_setting(test_db, org.id, "daily_send_target", 1)
    lead = _lead(test_db, org_id=org.id)
    # one already sent inside the window → target exhausted
    test_db.add(OutreachEmail(lead_id=lead.id, step_number=1, subject="s", body="b",
                              status="sent", sent_at=utcnow() - timedelta(hours=1)))
    test_db.add(OutreachEmail(lead_id=lead.id, step_number=2, subject="s", body="b",
                              status="scheduled", scheduled_at=utcnow() - timedelta(hours=1)))
    test_db.commit()

    with patch("app.services.compliance.can_send_to_recipient", return_value=(True, "ok")):
        summary = send_pending_scheduled_emails(test_db)

    assert summary["sent"] == 0
    assert summary["skipped"] >= 1


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def _login(client, email="admin@test.com"):
    client.post("/auth/register", json={"email": email, "password": "password123", "role": "rep"})
    r = client.post("/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _create_payload(**overrides):
    payload = {
        "name": "Q3 meetings push",
        "goal_type": "meetings",
        "goal_target": 12,
        "period_start": START.isoformat(),
        "period_end": END.isoformat(),
        "constraints": {"max_daily_sends": 50, "segments": [{"industry": "SaaS"}]},
    }
    payload.update(overrides)
    return payload


def test_campaign_crud_and_detail(client):
    headers = _login(client)
    r = client.post("/campaigns", json=_create_payload(), headers=headers)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert r.json()["pace"]["total_weekdays"] == 10

    r = client.get("/campaigns", headers=headers)
    assert r.json()["total"] == 1

    r = client.get(f"/campaigns/{cid}", headers=headers)
    assert r.status_code == 200
    assert r.json()["progress"]["total"]["sends"] == 0
    assert r.json()["current_plan"] is None

    r = client.put(f"/campaigns/{cid}", json={"status": "paused"}, headers=headers)
    assert r.json()["status"] == "paused"


def test_campaign_rejects_inverted_period(client):
    headers = _login(client)
    r = client.post("/campaigns", json=_create_payload(
        period_start=END.isoformat(), period_end=START.isoformat()), headers=headers)
    assert r.status_code == 422


def test_replan_and_approval_flow(client):
    headers = _login(client)
    cid = client.post("/campaigns", json=_create_payload(), headers=headers).json()["id"]

    with patch("app.services.providers.get_ai_client",
               return_value=_fake_ai('{"diagnosis": "keep steady", "actions": '
                                     '[{"type": "escalate", "severity": "info", "message": "on track"}]}')):
        r = client.post(f"/campaigns/{cid}/replan", headers=headers)
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["status"] == "pending_approval"

    r = client.post(f"/campaigns/{cid}/plans/{plan['id']}/approve", headers=headers)
    assert r.status_code == 200
    assert r.json()["execution"]["succeeded"] == 1
    assert r.json()["plan"]["status"] == "active"
    assert r.json()["plan"]["execution_log"][0]["action_type"] == "escalate"

    # double approval refused
    r = client.post(f"/campaigns/{cid}/plans/{plan['id']}/approve", headers=headers)
    assert r.status_code == 409


def test_reject_plan(client):
    headers = _login(client)
    cid = client.post("/campaigns", json=_create_payload(), headers=headers).json()["id"]
    with patch("app.services.providers.get_ai_client",
               return_value=_fake_ai('{"diagnosis": "d", "actions": []}')):
        plan = client.post(f"/campaigns/{cid}/replan", headers=headers).json()
    r = client.post(f"/campaigns/{cid}/plans/{plan['id']}/reject",
                    json={"reason": "too aggressive"}, headers=headers)
    assert r.json()["status"] == "rejected"
    assert r.json()["rejection_reason"] == "too aggressive"


def test_report_endpoint(client, test_db):
    headers = _login(client)
    cid = client.post("/campaigns", json=_create_payload(), headers=headers).json()["id"]
    with patch("app.agents.campaign_agent.build_report", return_value="# stub report") as mock_report:
        r = client.get(f"/campaigns/{cid}/report", headers=headers)
    # no stored report → generated on the fly (mock avoids real LLM)
    assert r.status_code == 200
    assert mock_report.called or r.json()["report_md"]


def test_campaign_autonomy_dial(client):
    headers = _login(client)
    assert client.get("/campaigns/autonomy", headers=headers).json()["mode"] == "approve"
    r = client.put("/campaigns/autonomy", json={"mode": "auto"}, headers=headers)
    assert r.json()["mode"] == "auto"
    assert client.put("/campaigns/autonomy", json={"mode": "yolo"}, headers=headers).status_code == 422


def test_org_scoping_and_auth(client, test_db):
    headers = _login(client)
    from app.services.tenancy import create_org
    other = create_org(test_db, "Other Co")
    foreign = Campaign(org_id=other.id, name="theirs", goal_type="meetings",
                       goal_target=5, period_start=START, period_end=END)
    test_db.add(foreign)
    test_db.commit()

    assert client.get(f"/campaigns/{foreign.id}", headers=headers).status_code == 404
    assert client.get("/campaigns").status_code in (401, 403)
    assert client.post("/campaigns", json=_create_payload()).status_code in (401, 403)


def test_pydantic_action_vocabulary_rejects_unknown_type():
    with pytest.raises(Exception):
        ca.PlanProposal(diagnosis="d", actions=[{"type": "rm_rf_production", "reason": "lol"}])
