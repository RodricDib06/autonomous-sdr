"""
Send-path regressions:

  - step 1 went out immediately in full-auto mode, skipping the recipient's
    local send window, the daily cap and the org target
  - the scheduler took 50 due emails unordered; when those were all held,
    sendable emails behind them starved every tick
  - a step held past its slot could fire back-to-back with the next step
  - LLM-written bodies were interpolated into the HTML part unescaped
"""
from datetime import datetime, timedelta
from unittest.mock import patch

from app.agents.outreach_agent import OutreachAgent, send_pending_scheduled_emails
from app.database.models import Lead, OutreachEmail, OutreachSequence

BERLIN_NIGHT = datetime(2026, 7, 1, 0, 30)    # 02:30 Berlin, 09:30 Tokyo

WINDOW = dict(
    OUTREACH_SEND_WINDOW_START=8, OUTREACH_SEND_WINDOW_END=18,
    OUTREACH_WEEKDAYS_ONLY=False, OUTREACH_DAILY_SEND_LIMIT=1000, SMTP_HOST="",
)


def _lead(db, email, tz):
    lead = Lead(name="L", email=email, company="C", timezone=tz, status="complete")
    db.add(lead)
    db.commit()
    return lead


def _email(db, lead, step, scheduled_at, status="scheduled"):
    e = OutreachEmail(lead_id=lead.id, step_number=step, subject="s", body="b",
                      status=status, scheduled_at=scheduled_at)
    db.add(e)
    db.commit()
    return e


def _run_scheduler(db, now=BERLIN_NIGHT):
    with patch.multiple("app.config.settings", **WINDOW), \
         patch("app.agents.outreach_agent.utcnow", return_value=now):
        return send_pending_scheduled_emails(db)


def test_held_emails_do_not_starve_sendable_ones(test_db):
    for i in range(60):
        lead = _lead(test_db, f"p{i}@firma.de", "Europe/Berlin")
        _email(test_db, lead, 2, datetime(2026, 6, 29, 12, 0))
    tokyo = _lead(test_db, "k@kaisha.jp", "Asia/Tokyo")
    late = _email(test_db, tokyo, 2, datetime(2026, 6, 30, 12, 0))

    summary = _run_scheduler(test_db)

    assert summary["sent"] == 1
    test_db.refresh(late)
    assert late.status == "sent"


def test_later_step_waits_for_held_earlier_step(test_db):
    lead = _lead(test_db, "k@kaisha.jp", "Asia/Tokyo")
    step1 = _email(test_db, lead, 1, datetime(2026, 6, 26, 9, 0))
    step2 = _email(test_db, lead, 2, datetime(2026, 6, 29, 9, 0))

    _run_scheduler(test_db)

    test_db.refresh(step1)
    test_db.refresh(step2)
    assert step1.status == "sent"
    assert step2.status == "scheduled"


def test_late_send_shifts_remaining_steps(test_db):
    lead = _lead(test_db, "k@kaisha.jp", "Asia/Tokyo")
    due = datetime(2026, 6, 28, 0, 30)          # three days late at BERLIN_NIGHT
    step1 = _email(test_db, lead, 1, due)
    step2 = _email(test_db, lead, 2, due + timedelta(days=3))

    _run_scheduler(test_db)

    test_db.refresh(step1)
    test_db.refresh(step2)
    assert step1.status == "sent"
    assert step2.scheduled_at == BERLIN_NIGHT + timedelta(days=3)


def test_step1_respects_recipient_window(test_db):
    lead = _lead(test_db, "hans@firma.de", "Europe/Berlin")
    seq = OutreachSequence(name="S", is_active=True, steps=[
        {"step": 1, "delay_days": 0, "subject_template": "s", "body_template": "b"},
    ])
    test_db.add(seq)
    test_db.commit()

    agent = OutreachAgent()
    with patch.multiple("app.config.settings", **{**WINDOW, "SMTP_HOST": "smtp.example.com"}), \
         patch("app.services.compliance.utcnow", return_value=BERLIN_NIGHT), \
         patch("app.services.email_verification.verify_lead_email", return_value="valid"), \
         patch("app.services.tenancy.get_org_setting",
               side_effect=lambda db, org, key, default=None: "auto" if key == "autonomy_mode" else default), \
         patch.object(agent, "_pick_sequence", return_value=seq), \
         patch.object(agent, "_personalise_with_judge", return_value=("s", "b", {})), \
         patch("app.services.provenance.ground_email", return_value={}), \
         patch.object(agent, "_send_email") as send:
        result = agent.run(test_db, lead.id, {"research": {}})

    send.assert_not_called()
    assert result["step1_send"].startswith("deferred")
    step1 = test_db.query(OutreachEmail).filter_by(lead_id=lead.id, step_number=1).one()
    assert step1.status == "scheduled"


def test_html_part_escapes_body(test_db):
    lead = _lead(test_db, "a@acme.com", None)
    email = _email(test_db, lead, 1, datetime(2026, 7, 1))
    email.body = "Cut onboarding to <10 minutes for R&D teams"
    test_db.commit()

    sent = {}

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def login(self, *a): pass
        def sendmail(self, frm, to, msg): sent["msg"] = msg

    with patch.multiple("app.config.settings", SMTP_HOST="smtp.example.com",
                        APP_BASE_URL="https://api.example.com",
                        OUTREACH_POSTAL_ADDRESS="1 Main St, Springfield"), \
         patch("app.services.mailbox_service.pick_mailbox", return_value=None), \
         patch("app.agents.outreach_agent.smtplib.SMTP_SSL", FakeSMTP):
        OutreachAgent()._send_email(test_db, email, lead.email)

    import email as email_lib
    parsed = email_lib.message_from_string(sent["msg"])
    html_part = next(p for p in parsed.walk() if p.get_content_type() == "text/html")
    html = html_part.get_payload(decode=True).decode()
    assert "&lt;10 minutes for R&amp;D" in html
