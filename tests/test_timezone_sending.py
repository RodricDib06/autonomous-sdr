"""
Tests for recipient-timezone inference and local-time send windows.
"""
from datetime import datetime
from unittest.mock import patch

from app.database.models import Lead, OutreachEmail
from app.services.timezone_service import infer_timezone, within_recipient_window
from app.services.compliance import can_send_to_recipient


def test_infer_timezone_from_cc_tld():
    assert infer_timezone("hans@firma.de") == "Europe/Berlin"
    assert infer_timezone("yuki@kaisha.co.jp") == "Asia/Tokyo"
    assert infer_timezone("amit@startup.in") == "Asia/Kolkata"
    assert infer_timezone("sam@company.com.au") == "Australia/Sydney"


def test_infer_timezone_generic_tld_returns_none():
    assert infer_timezone("jane@acme.com") is None
    assert infer_timezone("dev@startup.io") is None
    assert infer_timezone("not-an-email") is None


def test_within_recipient_window_local_morning():
    # 08:00 UTC Wednesday = 17:00 Tokyo — outside a 8-18 window? inside (17 < 18)
    now = datetime(2026, 7, 1, 8, 0)
    ok, reason = within_recipient_window("Asia/Tokyo", now, 8, 18, True)
    assert ok is True

    # 12:00 UTC Wednesday = 21:00 Tokyo — outside
    ok, reason = within_recipient_window("Asia/Tokyo", datetime(2026, 7, 1, 12, 0), 8, 18, True)
    assert ok is False
    assert "Tokyo" in reason


def test_within_recipient_window_local_weekend():
    # Friday 23:00 UTC = Saturday 08:00 Tokyo
    ok, reason = within_recipient_window("Asia/Tokyo", datetime(2026, 7, 3, 23, 0), 0, 24, True)
    assert ok is False
    assert "weekend" in reason.lower()


def test_within_recipient_window_unknown_tz():
    ok, _ = within_recipient_window(None, datetime(2026, 7, 1, 8, 0), 8, 18, True)
    assert ok is None
    ok, _ = within_recipient_window("Not/AZone", datetime(2026, 7, 1, 8, 0), 8, 18, True)
    assert ok is None


def test_can_send_to_recipient_falls_back_to_utc(test_db):
    lead = Lead(name="J", email="j@acme.com", company="C", timezone=None)
    with patch.multiple("app.config.settings",
                        OUTREACH_SEND_WINDOW_START=8, OUTREACH_SEND_WINDOW_END=18,
                        OUTREACH_WEEKDAYS_ONLY=False):
        ok, _ = can_send_to_recipient(lead, datetime(2026, 7, 1, 10, 0))
        assert ok is True
        ok, reason = can_send_to_recipient(lead, datetime(2026, 7, 1, 3, 0))
        assert ok is False
        assert "UTC" in reason


def test_sender_respects_recipient_local_night(test_db):
    """A German lead at 02:00 Berlin time is held even when UTC allows sends."""
    from app.agents.outreach_agent import send_pending_scheduled_emails
    lead = Lead(name="Hans", email="hans@firma.de", company="Firma", timezone="Europe/Berlin")
    test_db.add(lead)
    test_db.commit()
    email = OutreachEmail(
        lead_id=lead.id, step_number=2, subject="s", body="b",
        status="scheduled", scheduled_at=datetime(2026, 6, 30, 12, 0),
    )
    test_db.add(email)
    test_db.commit()

    fixed_now = datetime(2026, 7, 1, 0, 30)  # 02:30 Berlin (CEST)
    with patch.multiple("app.config.settings",
                        OUTREACH_SEND_WINDOW_START=8, OUTREACH_SEND_WINDOW_END=18,
                        OUTREACH_WEEKDAYS_ONLY=False, OUTREACH_DAILY_SEND_LIMIT=200,
                        SMTP_HOST=""), \
         patch("app.agents.outreach_agent.utcnow", return_value=fixed_now):
        summary = send_pending_scheduled_emails(test_db)

    assert summary["sent"] == 0
    assert summary["skipped"] == 1
    test_db.refresh(email)
    assert email.status == "scheduled"


def test_sender_sends_in_recipient_morning(test_db):
    """Same German lead at 10:00 Berlin time goes out."""
    from app.agents.outreach_agent import send_pending_scheduled_emails
    lead = Lead(name="Hans", email="hans@firma.de", company="Firma", timezone="Europe/Berlin")
    test_db.add(lead)
    test_db.commit()
    email = OutreachEmail(
        lead_id=lead.id, step_number=2, subject="s", body="b",
        status="scheduled", scheduled_at=datetime(2026, 6, 30, 12, 0),
    )
    test_db.add(email)
    test_db.commit()

    fixed_now = datetime(2026, 7, 1, 8, 0)  # 10:00 Berlin (CEST)
    with patch.multiple("app.config.settings",
                        OUTREACH_SEND_WINDOW_START=8, OUTREACH_SEND_WINDOW_END=18,
                        OUTREACH_WEEKDAYS_ONLY=False, OUTREACH_DAILY_SEND_LIMIT=200,
                        SMTP_HOST=""), \
         patch("app.agents.outreach_agent.utcnow", return_value=fixed_now):
        summary = send_pending_scheduled_emails(test_db)

    assert summary["sent"] == 1
    test_db.refresh(email)
    assert email.status == "sent"
