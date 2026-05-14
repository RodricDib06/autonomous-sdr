"""Tests for A/B testing service: chi-square calculation, find_winner, record_event."""
import pytest
from unittest.mock import MagicMock, patch
from app.services.ab_testing import _chi_square_p, _chi2_p_approx, find_winner, record_event


# ---------------------------------------------------------------------------
# _chi_square_p — statistical core
# ---------------------------------------------------------------------------

def test_identical_proportions_gives_high_p():
    # Same conversion rate → no difference → p should be well above significance threshold
    p = _chi_square_p(10, 100, 10, 100)
    assert p > 0.5


def test_zero_total_returns_1():
    assert _chi_square_p(0, 0, 5, 100) == 1.0
    assert _chi_square_p(5, 100, 0, 0) == 1.0


def test_clearly_different_proportions_low_p():
    # 80% vs 10% with 200 samples each → very significant
    p = _chi_square_p(160, 200, 20, 200)
    assert p < 0.05


def test_no_conversions_returns_1():
    # 0 conversions on both sides → no difference to detect
    p = _chi_square_p(0, 100, 0, 100)
    assert p == 1.0


def test_p_value_is_between_0_and_1():
    p = _chi_square_p(30, 100, 10, 100)
    assert 0.0 <= p <= 1.0


def test_chi2_p_approx_zero_returns_1():
    assert _chi2_p_approx(0) == 1.0


def test_chi2_p_approx_large_value_near_0():
    # chi2=20 corresponds to p << 0.001
    p = _chi2_p_approx(20.0)
    assert p < 0.01


def test_chi2_p_approx_boundary_3_84():
    # chi2=3.841 is the 0.05 threshold for 1 df — approximation should be in the right ballpark
    p_low = _chi2_p_approx(3.841)
    p_high = _chi2_p_approx(0.1)
    # The approximation is monotone: higher chi2 → lower p
    assert p_low < p_high


# ---------------------------------------------------------------------------
# find_winner — end-to-end with mocked DB
# ---------------------------------------------------------------------------

def _mock_db_with_results(results):
    """Build a minimal mock DB that returns the given dicts from get_test_results."""
    db = MagicMock()
    return db, results


def test_find_winner_returns_none_when_not_enough_variants():
    db = MagicMock()
    with patch("app.services.ab_testing.get_test_results", return_value=[]):
        result = find_winner(db)
    assert result is None


def test_find_winner_returns_none_when_below_min_sample():
    db = MagicMock()
    small_results = [
        {"variant": "A", "sample_size": 5, "conversion_rate": 0.5, "emails_sent": 5, "conversions": 2, "emails_opened": 3, "replies": 1},
        {"variant": "B", "sample_size": 5, "conversion_rate": 0.1, "emails_sent": 5, "conversions": 0, "emails_opened": 1, "replies": 0},
    ]
    with patch("app.services.ab_testing.get_test_results", return_value=small_results):
        result = find_winner(db)
    assert result is None


def test_find_winner_returns_none_when_not_significant():
    db = MagicMock()
    # Similar conversion rates → p > 0.05
    similar_results = [
        {"variant": "A", "sample_size": 50, "conversion_rate": 0.20, "emails_sent": 50},
        {"variant": "B", "sample_size": 50, "conversion_rate": 0.18, "emails_sent": 50},
    ]
    with patch("app.services.ab_testing.get_test_results", return_value=similar_results):
        with patch("app.services.ab_testing._chi_square_p", return_value=0.42):
            result = find_winner(db)
    assert result is None


def test_find_winner_returns_winner_when_significant():
    db = MagicMock()
    strong_results = [
        {"variant": "A", "sample_size": 100, "conversion_rate": 0.40, "emails_sent": 100},
        {"variant": "B", "sample_size": 100, "conversion_rate": 0.05, "emails_sent": 100},
    ]
    with patch("app.services.ab_testing.get_test_results", return_value=strong_results):
        with patch("app.services.ab_testing._chi_square_p", return_value=0.001):
            result = find_winner(db)
    assert result is not None
    assert result["variant"] == "A"
    assert result["is_winner"] is True
    assert result["p_value"] == 0.001


# ---------------------------------------------------------------------------
# record_event — counter update logic
# ---------------------------------------------------------------------------

def _make_email(sequence_id="seq-1", variant="A"):
    email = MagicMock()
    email.id = "email-1"
    email.sequence_id = sequence_id
    seq = MagicMock()
    seq.id = sequence_id
    seq.ab_variant = variant
    return email, seq


def test_record_event_sent_increments_emails_sent():
    email, seq = _make_email()
    result_row = MagicMock()
    result_row.emails_sent = 5

    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [email, seq, result_row]

    record_event(db, "email-1", "sent")

    assert result_row.emails_sent == 6
    db.commit.assert_called_once()


def test_record_event_opened_increments_emails_opened():
    email, seq = _make_email()
    result_row = MagicMock()
    result_row.emails_opened = 2

    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [email, seq, result_row]

    record_event(db, "email-1", "opened")

    assert result_row.emails_opened == 3


def test_record_event_no_sequence_is_noop():
    email = MagicMock()
    email.sequence_id = None
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = email

    record_event(db, "email-1", "opened")

    db.commit.assert_not_called()


def test_record_event_email_not_found_is_noop():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    record_event(db, "missing-email-id", "sent")

    db.commit.assert_not_called()
