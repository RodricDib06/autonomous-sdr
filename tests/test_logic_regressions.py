"""
Regression tests for logic bugs that produced no error, just wrong data:

  - merging two leads deleted the duplicate's emails, conversations and even
    the enrichment/verdict rows it claimed to move
  - check-duplicate matched the lead's own email first, short-circuiting the
    fuzzy pass, so near-duplicates were never reported
  - duplicate checks spanned orgs: a prospect in org B blocked org A
  - an admin could demote the org's last admin and lock everyone out
  - demo seeding left leads without an org, invisible to every scoped user
"""
from unittest.mock import patch

from app.agents.orchestrator_agent import OrchestratorAgent
from app.database.models import (
    Conversation, Enrichment, Lead, OutreachEmail, User, Verdict,
)
from app.services.auth_service import hash_password
from app.services.deduplication import DeduplicationService
from app.services.tenancy import create_org, get_default_org


def _login(client, email, password="password123"):
    r = client.post("/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _admin(client):
    client.post("/auth/register", json={"email": "admin@test.com", "password": "password123", "role": "rep"})
    return _login(client, "admin@test.com")


def _lead(db, org_id, email, name="Jon Smith", company="Acme"):
    lead = Lead(name=name, email=email, company=company, org_id=org_id, status="complete")
    db.add(lead)
    db.commit()
    return lead


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

def test_merge_keeps_every_child_row(test_db):
    org = get_default_org(test_db).id
    primary = _lead(test_db, org, "jon@acme.com")
    dup = _lead(test_db, org, "jon.smith@acme.com")
    test_db.add_all([
        Enrichment(lead_id=dup.id, job_title="VP Sales"),
        Verdict(lead_id=dup.id, final_verdict="Hot"),
        OutreachEmail(lead_id=dup.id, step_number=1, subject="s", body="b", status="sent"),
        Conversation(lead_id=dup.id, channel="email", messages=[]),
    ])
    test_db.commit()
    dup.enrichments, dup.verdicts  # loaded in-session, as the merge route does

    assert DeduplicationService(test_db).merge_leads(primary.id, dup.id)
    test_db.expire_all()

    assert test_db.get(Lead, dup.id) is None
    for model in (Enrichment, Verdict, OutreachEmail, Conversation):
        rows = test_db.query(model).all()
        assert [r.lead_id for r in rows] == [primary.id], model.__name__


def test_merge_keeps_primarys_own_verdict(test_db):
    org = get_default_org(test_db).id
    primary = _lead(test_db, org, "a@acme.com")
    dup = _lead(test_db, org, "b@acme.com")
    test_db.add_all([Verdict(lead_id=primary.id, final_verdict="Warm"),
                     Verdict(lead_id=dup.id, final_verdict="Cold")])
    test_db.commit()

    DeduplicationService(test_db).merge_leads(primary.id, dup.id)
    test_db.expire_all()
    assert [v.final_verdict for v in test_db.query(Verdict).all()] == ["Warm"]


def test_merge_with_itself_is_refused(test_db):
    lead = _lead(test_db, get_default_org(test_db).id, "a@acme.com")
    assert DeduplicationService(test_db).merge_leads(lead.id, lead.id) is False
    assert test_db.get(Lead, lead.id) is not None


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

def test_check_duplicate_finds_fuzzy_match(client, test_session_factory):
    headers = _admin(client)
    db = test_session_factory()
    org = get_default_org(db).id
    lead = _lead(db, org, "jon@acme.com", name="Jon Smith", company="Acme Inc")
    near = _lead(db, org, "j.smith@acme.io", name="Jon Smith", company="Acme")
    lead_id, near_id = lead.id, near.id
    db.close()

    body = client.post(f"/leads/{lead_id}/check-duplicate", headers=headers).json()
    assert body["has_duplicates"] is True
    assert [d["id"] for d in body["potential_duplicates"]] == [near_id]


def test_email_duplicates_are_per_org(test_db):
    org_a = get_default_org(test_db).id
    org_b = create_org(test_db, "Other").id
    _lead(test_db, org_b, "shared@prospect.com")

    dedup = DeduplicationService(test_db)
    assert dedup.find_duplicates_by_email("shared@prospect.com", org_id=org_a) == []
    assert len(dedup.find_duplicates_by_email("shared@prospect.com", org_id=org_b)) == 1


def test_orchestrator_duplicate_check_is_per_org(test_db):
    org_a = get_default_org(test_db).id
    org_b = create_org(test_db, "Other").id
    _lead(test_db, org_b, "shared@prospect.com")
    mine = _lead(test_db, org_a, "shared@prospect.com")

    is_dup, _ = OrchestratorAgent()._check_duplicate(test_db, mine)
    assert is_dup is False


def test_public_ingest_ignores_other_orgs_leads(client, test_session_factory):
    db = test_session_factory()
    other = _lead(db, create_org(db, "Other").id, "shared@prospect.com")
    other_id = other.id
    db.close()

    with patch("app.routers.ingest.push_lead_job"):
        r = client.post("/ingest/form", json={
            "name": "Shared", "email": "shared@prospect.com", "company": "Prospect",
        })
    assert r.status_code == 200, r.text
    assert r.json().get("status") != "duplicate"
    assert r.json().get("lead_id") != other_id


# ---------------------------------------------------------------------------
# Last admin
# ---------------------------------------------------------------------------

def test_cannot_demote_last_admin(client, test_session_factory):
    headers = _admin(client)
    db = test_session_factory()
    me = db.query(User).filter_by(email="admin@test.com").one().id
    db.close()
    r = client.put(f"/auth/users/{me}/role?role=rep", headers=headers)
    assert r.status_code == 400


def test_can_demote_admin_when_another_remains(client, test_session_factory):
    headers = _admin(client)
    db = test_session_factory()
    other = User(email="second@test.com", password_hash=hash_password("x"), role="admin",
                 org_id=get_default_org(db).id)
    db.add(other)
    db.commit()
    other_id = other.id
    db.close()
    assert client.put(f"/auth/users/{other_id}/role?role=rep", headers=headers).status_code == 200


# ---------------------------------------------------------------------------
# Demo seed
# ---------------------------------------------------------------------------

def test_demo_seed_assigns_org(test_db):
    from scripts.seed_demo_data import seed

    org = create_org(test_db, "Wizard Org").id
    seed(test_db, org_id=org)
    total = test_db.query(Lead).count()
    assert total > 0
    assert test_db.query(Lead).filter(Lead.org_id == org).count() == total


# ---------------------------------------------------------------------------
# Learning loops see real wins
# ---------------------------------------------------------------------------

def _outcomes(db, n_won, n_lost, won_status="won"):
    """Wins via the API's own vocabulary ("won"), not the seed's "converted"."""
    org = get_default_org(db).id
    for i in range(n_won + n_lost):
        won = i < n_won
        lead = Lead(name=f"L{i}", email=f"l{i}@x.com", company="C", org_id=org, status="complete",
                    conversion_status=won_status if won else "lost")
        db.add(lead)
        db.flush()
        hi, lo = (0.9, 0.2) if won else (0.2, 0.8)
        db.add(Verdict(lead_id=lead.id, final_verdict="Hot" if won else "Cold", confidence_score=0.8,
                       bant_scores={"budget": 0.5, "authority": hi, "need": hi, "timeline": lo}))
    db.commit()


def test_optimizer_counts_won_deals(test_db):
    from app.services.optimization_loop import run_optimization
    _outcomes(test_db, n_won=10, n_lost=6)
    assert run_optimization(test_db)["status"] == "ran"


def test_ml_scorer_trains_on_won_deals(test_db):
    from app.services.ml_scorer import retrain
    _outcomes(test_db, n_won=4, n_lost=4)
    assert retrain(test_db) is True


def test_lookalike_centroid_uses_won_deals(test_db):
    from app.services.lookalike_scorer import compute_converted_centroid
    _outcomes(test_db, n_won=6, n_lost=0)
    assert compute_converted_centroid(test_db) is not None


# ---------------------------------------------------------------------------
# Email matching is exact, not LIKE
# ---------------------------------------------------------------------------

def test_bounce_does_not_hit_wildcard_lookalike(test_db):
    from app.services.bounce_service import handle_bounce
    org = get_default_org(test_db).id
    bystander = _lead(test_db, org, "jxdoe@acme.com")
    target = _lead(test_db, org, "j_doe@acme.com")

    handle_bounce(test_db, "j_doe@acme.com", True, "550 no such user", org_id=org)
    test_db.expire_all()

    assert test_db.get(Lead, target.id).email_verification_status == "undeliverable"
    assert test_db.get(Lead, bystander.id).email_verification_status != "undeliverable"


def test_inbound_reply_matches_exact_sender(test_db):
    from types import SimpleNamespace
    from app.services.mailbox_service import _process_inbound
    org = get_default_org(test_db).id
    _lead(test_db, org, "jxdoe@acme.com")
    mailbox = SimpleNamespace(org_id=org, email="sdr@us.com")

    with patch("app.services.reply_service.handle_reply") as handle:
        outcome = _process_inbound(test_db, mailbox, "j_doe@acme.com", "Re: hi", "Sounds good")
    assert outcome == "ignored"
    handle.assert_not_called()


def test_reply_applies_bayesian_boost(test_db):
    from app.services.reply_classifier import Classification
    from app.services.reply_service import handle_reply
    lead = _lead(test_db, get_default_org(test_db).id, "warm@acme.com")
    test_db.add(Verdict(lead_id=lead.id, final_verdict="Warm", confidence_score=0.5,
                        bant_scores={"budget": 0.5, "authority": 0.5, "need": 0.5, "timeline": 0.5}))
    test_db.commit()

    interested = Classification(category="interested", confidence=0.9)
    with patch("app.services.reply_service.classify_reply", return_value=interested):
        handle_reply(test_db, lead, "Yes, let's talk next week")
    test_db.expire_all()
    verdict = test_db.query(Verdict).filter_by(lead_id=lead.id).one()
    assert verdict.bant_scores["need"] > 0.5


# ---------------------------------------------------------------------------
# GDPR erasure leaves no dangling foreign keys
# ---------------------------------------------------------------------------

def test_erasure_succeeds_with_crm_log_and_referrals(test_db):
    """SQLite skips FK checks by default — turn them on so this fails like Postgres did."""
    from sqlalchemy import text
    from app.database.models import CrmSyncLog, LLMCall
    from app.services.gdpr_service import erase_lead

    test_db.execute(text("PRAGMA foreign_keys=ON"))
    org = get_default_org(test_db).id
    lead = _lead(test_db, org, "erase.me@acme.com")
    child = Lead(name="Ref", email="ref@acme.com", company="Acme", org_id=org, referred_by_lead_id=lead.id)
    test_db.add_all([
        child,
        CrmSyncLog(lead_id=lead.id, org_id=org, direction="outbound", event_type="contact.upsert"),
        LLMCall(lead_id=lead.id, provider="groq", model="m"),
    ])
    test_db.commit()

    result = erase_lead(test_db, lead, requested_by_id=None)
    test_db.expire_all()

    assert result["purged"]["llm_calls_anonymised"] == 1
    assert test_db.query(Lead).filter_by(email="erase.me@acme.com").count() == 0
    assert test_db.get(Lead, child.id).referred_by_lead_id is None
    assert test_db.query(CrmSyncLog).one().lead_id is None
