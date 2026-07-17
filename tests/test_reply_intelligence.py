"""
Tests for reply intelligence (Phase 8).

Coverage:
  - keyword classifier: every category, referral extraction, precedence
    (OOO beats interest phrases), empty text, LLM fallback path
  - handle_reply rewiring: unsubscribe still wins; OOO does NOT cancel the
    cadence or count as a reply (the bug this phase fixes); normal replies
    keep today's semantics; classification stored on the conversation;
    objections flag needs_human
  - referral action creates a linked lead exactly once
  - not_now schedules re-engagement; the daily job requeues exactly once
  - objections aggregation + /analytics/objections + planner snapshot feed
"""

from datetime import timedelta
from unittest.mock import MagicMock

from app.database.models import Conversation, Lead, LeadEvent, OutreachEmail
from app.services.reply_classifier import aggregate_objections, classify_reply
from app.services.reply_service import handle_reply, process_due_reengagements
from app.services.tenancy import get_default_org
from app.utils.time import utcnow


def _lead(db, email="jane@acme.io", org_id=None, **kwargs):
    lead = Lead(name="Jane", email=email, company="Acme", org_id=org_id, **kwargs)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def _cadence(db, lead, scheduled_steps=2):
    sent = OutreachEmail(lead_id=lead.id, step_number=1, subject="s", body="b",
                         status="sent", sent_at=utcnow() - timedelta(hours=2))
    db.add(sent)
    for i in range(scheduled_steps):
        db.add(OutreachEmail(lead_id=lead.id, step_number=i + 2, subject="s", body="b",
                             status="scheduled", scheduled_at=utcnow() + timedelta(days=i + 1)))
    db.commit()
    return sent


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

def test_keyword_categories():
    cases = {
        "I'm out of office until Monday, limited access to email.": ("auto_reply", None),
        "You should talk to Sarah Miller, she owns this: sarah@acme.io": ("referral", None),
        "I'm not the right person for this.": ("wrong_person", None),
        "Interesting but circle back next quarter.": ("not_now", None),
        "We have no budget for new tools this year.": ("objection", "price"),
        "We already use Outreach and are happy with our current setup.": ("objection", "competitor"),
        "This is not a priority for us.": ("objection", "no_need"),
        "How did you get my email? Is this spam?": ("objection", "trust"),
        "Sounds interesting — let's talk next week.": ("interested", None),
        "Thanks for reaching out. Regards, Jane": ("other", None),
    }
    for text, (category, subtype) in cases.items():
        result = classify_reply(text)
        assert result.category == category, f"{text!r} → {result.category}, expected {category}"
        assert result.subtype == subtype, f"{text!r} subtype {result.subtype} != {subtype}"


def test_ooo_outranks_interest_phrases():
    result = classify_reply("Out of office. For anything interesting, I'll respond when I return.")
    assert result.category == "auto_reply"


def test_referral_extraction_skips_sender():
    result = classify_reply(
        "Please reach out to Tom Weber (tom.weber@acme.io) instead.",
        sender_email="jane@acme.io",
    )
    assert result.category == "referral"
    assert result.extracted["referral_email"] == "tom.weber@acme.io"
    assert result.extracted["referral_name"] == "Tom Weber"


def test_llm_fallback_when_rules_inconclusive():
    client = MagicMock()
    client.generate.return_value = '{"category": "interested", "confidence": 0.7}'
    result = classify_reply("Hmm, das klingt eventuell relevant für uns.", ai_client=client)
    assert result.category == "interested"
    assert result.method == "llm"

    client.generate.side_effect = RuntimeError("down")
    result = classify_reply("Hmm, das klingt eventuell relevant für uns.", ai_client=client)
    assert result.category == "other"  # never raises


def test_empty_text_is_other():
    assert classify_reply("").category == "other"


# ---------------------------------------------------------------------------
# handle_reply rewiring
# ---------------------------------------------------------------------------

def test_unsubscribe_still_wins_over_everything(test_db):
    lead = _lead(test_db)
    _cadence(test_db, lead)
    result = handle_reply(test_db, lead, "Unsubscribe me. I'm also out of office.")
    assert result["status"] == "unsubscribed"
    scheduled = test_db.query(OutreachEmail).filter_by(status="scheduled").count()
    assert scheduled == 0


def test_ooo_does_not_cancel_cadence_or_mark_replied(test_db):
    lead = _lead(test_db)
    sent = _cadence(test_db, lead, scheduled_steps=2)

    result = handle_reply(test_db, lead, "I am out of office until August 3rd.")

    assert result["status"] == "auto_reply"
    test_db.refresh(sent)
    assert sent.status == "sent"  # NOT replied
    assert test_db.query(OutreachEmail).filter_by(status="scheduled").count() == 2
    conversation = test_db.query(Conversation).filter_by(lead_id=lead.id).first()
    assert conversation.classification["category"] == "auto_reply"


def test_normal_reply_keeps_existing_semantics(test_db):
    lead = _lead(test_db)
    sent = _cadence(test_db, lead, scheduled_steps=2)

    result = handle_reply(test_db, lead, "Sounds interesting, tell me more.")

    assert result["status"] == "replied"
    assert result["cancelled_emails"] == 2
    assert result["classification"]["category"] == "interested"
    test_db.refresh(sent)
    assert sent.status == "replied"


def test_objection_flags_needs_human_and_never_argues(test_db):
    lead = _lead(test_db)
    _cadence(test_db, lead)
    result = handle_reply(test_db, lead, "We already use Outreach and are happy with it.")

    assert result["classification"]["subtype"] == "competitor"
    conversation = test_db.query(Conversation).filter_by(lead_id=lead.id).first()
    assert conversation.needs_human is True
    assert conversation.classification["category"] == "objection"


def test_referral_creates_linked_lead_once(test_db):
    org = get_default_org(test_db)
    lead = _lead(test_db, org_id=org.id)
    _cadence(test_db, lead)

    result = handle_reply(
        test_db, lead, "You should talk to Sarah Miller — sarah@acme.io handles tooling."
    )

    assert result["referral_created"] is True
    referred = test_db.query(Lead).filter(Lead.email == "sarah@acme.io").first()
    assert referred is not None
    assert referred.referred_by_lead_id == lead.id
    assert referred.org_id == org.id
    assert referred.source == "referral"
    assert "gave-referral" in lead.tags

    # Same referral again → no duplicate
    result2 = handle_reply(test_db, lead, "As I said, talk to sarah@acme.io.")
    assert result2["referral_created"] is False
    assert test_db.query(Lead).filter(Lead.email == "sarah@acme.io").count() == 1


def test_wrong_person_tagged(test_db):
    lead = _lead(test_db)
    _cadence(test_db, lead)
    handle_reply(test_db, lead, "I'm not the right person for this.")
    assert "wrong-person" in lead.tags


# ---------------------------------------------------------------------------
# not_now → re-engagement
# ---------------------------------------------------------------------------

def test_not_now_schedules_reengagement(test_db):
    lead = _lead(test_db)
    _cadence(test_db, lead)
    result = handle_reply(test_db, lead, "Circle back next quarter please.")

    assert "reengage_at" in result
    event = test_db.query(LeadEvent).filter_by(event_type="reply.not_now").first()
    assert event is not None
    assert "revisit-later" in lead.tags


def test_reengagement_job_requeues_exactly_once(test_db):
    lead = _lead(test_db)
    lead.status = "complete"
    test_db.commit()
    from app.database import crud
    crud.append_lead_event(test_db, lead.id, "reply.not_now", payload={
        "resume_at": (utcnow() - timedelta(days=1)).isoformat(),
    })

    summary = process_due_reengagements(test_db)
    assert summary["requeued"] == 1
    test_db.refresh(lead)
    assert lead.status == "pending"
    assert lead.reengagement_count == 1

    # Second run: the reengaged marker prevents a repeat
    assert process_due_reengagements(test_db)["requeued"] == 0


def test_reengagement_job_ignores_future_dates(test_db):
    lead = _lead(test_db)
    from app.database import crud
    crud.append_lead_event(test_db, lead.id, "reply.not_now", payload={
        "resume_at": (utcnow() + timedelta(days=30)).isoformat(),
    })
    assert process_due_reengagements(test_db)["requeued"] == 0


# ---------------------------------------------------------------------------
# Aggregation + API + planner feed
# ---------------------------------------------------------------------------

def _objection_conversation(db, lead, subtype, text):
    conversation = Conversation(
        lead_id=lead.id, channel="email",
        messages=[{"role": "lead", "content": text, "timestamp": utcnow().isoformat()}],
        classification={"category": "objection", "subtype": subtype,
                        "confidence": 0.85, "method": "keyword", "extracted": {}},
    )
    db.add(conversation)
    db.commit()


def test_aggregate_objections(test_db):
    from app.database.models import Enrichment
    org = get_default_org(test_db)
    a = _lead(test_db, email="a@x.io", org_id=org.id)
    b = _lead(test_db, email="b@y.io", org_id=org.id)
    test_db.add(Enrichment(lead_id=a.id, industry="SaaS"))
    test_db.commit()
    _objection_conversation(test_db, a, "competitor", "we already use X")
    _objection_conversation(test_db, b, "competitor", "happy with current vendor")
    _objection_conversation(test_db, b, "price", "no budget")

    result = aggregate_objections(test_db, org_id=org.id)

    assert result["total_objections"] == 3
    assert result["by_subtype"]["competitor"] == 2
    assert result["top"][0]["subtype"] == "competitor"
    assert result["by_industry"]["SaaS"]["competitor"] == 1
    assert len(result["examples"]["competitor"]) == 2


def test_objections_endpoint(client, test_db):
    client.post("/auth/register", json={"email": "admin@test.com", "password": "password123", "role": "rep"})
    r = client.post("/auth/login", json={"email": "admin@test.com", "password": "password123"})
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    org = get_default_org(test_db)
    lead = _lead(test_db, org_id=org.id)
    _objection_conversation(test_db, lead, "price", "too expensive for us")

    resp = client.get("/analytics/objections", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["by_subtype"]["price"] == 1

    assert client.get("/analytics/objections").status_code in (401, 403)


def test_planner_snapshot_includes_objections(test_db):
    from app.services.campaign_metrics import build_snapshot
    from tests.test_campaigns import _campaign

    org = get_default_org(test_db)
    lead = _lead(test_db, org_id=org.id)
    _objection_conversation(test_db, lead, "competitor", "we already use a tool")

    campaign = _campaign(test_db, org_id=org.id)
    snapshot = build_snapshot(test_db, campaign)

    assert snapshot["top_objections"][0]["subtype"] == "competitor"
    assert "competitor" in snapshot["objection_examples"]
