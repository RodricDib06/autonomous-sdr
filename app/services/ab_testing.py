"""
A/B Testing Service for Outreach Sequences

Tracks per-variant metrics (sent, opened, replied, booked, converted) and
computes statistical significance so the winning variant can be promoted.

PoC: all stats live in the `ab_test_results` Postgres table.
     Uses a simple Chi-square test for significance (no external library needed).

# PRODUCTION upgrades:
#   - Use a proper experimentation platform (LaunchDarkly, Statsig, GrowthBook)
#     for bucketing, hold-outs, and Bayesian bandits.
#   - Emit events to a data warehouse (BigQuery / Snowflake) and run analysis
#     in a BI tool (Looker, Metabase) for richer funnel breakdowns.
#   - Add multi-armed bandit routing (epsilon-greedy or Thompson sampling) so
#     the agent shifts traffic to the winner before statistical significance is reached.
"""

import logging
import math
from sqlalchemy.orm import Session

from app.database.models import OutreachEmail, OutreachSequence, ABTestResult
from app.services.bandit import get_bandit_state
from app.utils.time import utcnow

log = logging.getLogger(__name__)

# Minimum emails sent before we declare a winner (avoid noise at low N)
_MIN_SAMPLE = 30
# p-value threshold for significance
_P_VALUE_THRESHOLD = 0.05


# ---------------------------------------------------------------------------
# Event tracking
# ---------------------------------------------------------------------------

def record_event(db: Session, email_id: str, event: str) -> None:
    """
    Record an engagement event for an outreach email and update A/B counters.

    event: "sent" | "opened" | "replied" | "booked" | "converted"
    """
    email = db.query(OutreachEmail).filter(OutreachEmail.id == email_id).first()
    if not email or not email.sequence_id:
        return

    sequence = db.query(OutreachSequence).filter(OutreachSequence.id == email.sequence_id).first()
    if not sequence or not sequence.ab_variant:
        return

    result = (
        db.query(ABTestResult)
        .filter(ABTestResult.sequence_id == sequence.id, ABTestResult.variant == sequence.ab_variant)
        .first()
    )
    if not result:
        result = ABTestResult(
            sequence_id=sequence.id,
            variant=sequence.ab_variant,
        )
        db.add(result)

    # Update the relevant counter
    if event == "sent":
        result.emails_sent = (result.emails_sent or 0) + 1
    elif event == "opened":
        result.emails_opened = (result.emails_opened or 0) + 1
    elif event == "replied":
        result.replies = (result.replies or 0) + 1
    elif event == "booked":
        result.meetings_booked = (result.meetings_booked or 0) + 1
    elif event == "converted":
        result.conversions = (result.conversions or 0) + 1

    result.updated_at = utcnow()
    db.commit()
    log.debug(f"[ab] event={event} → variant={sequence.ab_variant} sequence={sequence.id}")


# ---------------------------------------------------------------------------
# Significance testing
# ---------------------------------------------------------------------------

def get_test_results(db: Session, sequence_ids: list[str] | None = None) -> list[dict]:
    """
    Return per-variant metrics, significance status, and Thompson Sampling bandit state.

    Each result includes:
      - Standard funnel rates (open, reply, booking, conversion)
      - bandit_alpha, bandit_beta: Beta distribution parameters
      - bandit_mean: posterior mean conversion-rate estimate
      - bandit_win_probability: P(this variant wins) via Monte Carlo
    """
    query = db.query(ABTestResult)
    if sequence_ids:
        query = query.filter(ABTestResult.sequence_id.in_(sequence_ids))

    rows = query.all()
    base_results = []
    for row in rows:
        sent = row.emails_sent or 0
        opened = row.emails_opened or 0
        replied = row.replies or 0
        booked = row.meetings_booked or 0
        converted = row.conversions or 0

        base_results.append({
            "sequence_id": row.sequence_id,
            "variant": row.variant,
            "emails_sent": sent,
            "emails_opened": opened,
            "open_rate": round(opened / sent, 4) if sent > 0 else 0.0,
            "reply_rate": round(replied / sent, 4) if sent > 0 else 0.0,
            "booking_rate": round(booked / sent, 4) if sent > 0 else 0.0,
            "conversion_rate": round(converted / sent, 4) if sent > 0 else 0.0,
            "conversions": converted,
            "sample_size": sent,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        })

    # Attach Thompson Sampling bandit state — uses n_simulations=500 for speed
    bandit_input = [
        {"id": r["sequence_id"], "ab_variant": r["variant"],
         "emails_sent": r["emails_sent"], "conversions": r["conversions"]}
        for r in base_results
    ]
    try:
        bandit_enriched = get_bandit_state(bandit_input, n_simulations=500)
        bandit_by_id = {b["id"]: b for b in bandit_enriched}
        for r in base_results:
            bs = bandit_by_id.get(r["sequence_id"], {})
            r["bandit_alpha"] = bs.get("bandit_alpha")
            r["bandit_beta"] = bs.get("bandit_beta")
            r["bandit_mean"] = bs.get("bandit_mean")
            r["bandit_win_probability"] = bs.get("bandit_win_probability")
    except Exception as e:
        log.warning(f"[ab] bandit state computation failed: {e}")

    return base_results


def find_winner(db: Session) -> dict | None:
    """
    Compare all active A/B variants. Return the winning variant dict if one is
    statistically significant, else None.

    Uses a one-tailed proportion z-test on conversion_rate.
    """
    results = get_test_results(db)
    if len(results) < 2:
        return None

    # Filter to variants with enough data
    eligible = [r for r in results if r["sample_size"] >= _MIN_SAMPLE]
    if len(eligible) < 2:
        log.info(f"[ab] Not enough data yet (need {_MIN_SAMPLE} per variant, have {[r['sample_size'] for r in results]})")
        return None

    # Sort by conversion rate descending
    eligible.sort(key=lambda r: r["conversion_rate"], reverse=True)
    best = eligible[0]
    second = eligible[1]

    p_value = _chi_square_p(
        best["conversions"] if "conversions" in best else int(best["conversion_rate"] * best["sample_size"]),
        best["sample_size"],
        second["conversions"] if "conversions" in second else int(second["conversion_rate"] * second["sample_size"]),
        second["sample_size"],
    )

    if p_value < _P_VALUE_THRESHOLD:
        log.info(
            f"[ab] Winner found: variant={best['variant']} "
            f"conv_rate={best['conversion_rate']:.2%} p={p_value:.4f}"
        )
        return {**best, "p_value": p_value, "is_winner": True}

    log.info(f"[ab] No winner yet. Best: {best['variant']} conv={best['conversion_rate']:.2%}, p={p_value:.4f}")
    return None


def promote_winner(db: Session, winning_sequence_id: str) -> None:
    """
    Deactivate all other sequences and keep only the winner active.
    Call this after find_winner() confirms significance.
    """
    all_sequences = db.query(OutreachSequence).all()
    for seq in all_sequences:
        seq.is_active = seq.id == winning_sequence_id
    db.commit()
    log.info(f"[ab] Promoted winner: sequence {winning_sequence_id} — all others deactivated")


# ---------------------------------------------------------------------------
# Stats helper — Chi-square test for two proportions
# ---------------------------------------------------------------------------

def _chi_square_p(a_conv: int, a_total: int, b_conv: int, b_total: int) -> float:
    """
    Compute approximate p-value for difference between two proportions
    using a chi-square test with Yates' continuity correction.

    Returns p-value (lower = more significant).
    """
    if a_total == 0 or b_total == 0:
        return 1.0

    n = a_total + b_total
    obs_a_yes = a_conv
    obs_a_no = a_total - a_conv
    obs_b_yes = b_conv
    obs_b_no = b_total - b_conv

    total_yes = obs_a_yes + obs_b_yes
    total_no = obs_a_no + obs_b_no

    if total_yes == 0 or total_no == 0:
        return 1.0

    # Expected counts
    exp_a_yes = a_total * total_yes / n
    exp_a_no = a_total * total_no / n
    exp_b_yes = b_total * total_yes / n
    exp_b_no = b_total * total_no / n

    def _term(obs, exp):
        return (abs(obs - exp) - 0.5) ** 2 / exp if exp > 0 else 0

    chi2 = _term(obs_a_yes, exp_a_yes) + _term(obs_a_no, exp_a_no) + \
           _term(obs_b_yes, exp_b_yes) + _term(obs_b_no, exp_b_no)

    # Approximate p-value from chi-square CDF with 1 degree of freedom
    return _chi2_p_approx(chi2)


def _chi2_p_approx(chi2: float) -> float:
    """Approximate p-value for chi-square with 1 df using regularised gamma function."""
    if chi2 <= 0:
        return 1.0
    # survival function: p = 1 - regularised_gamma(0.5, chi2/2)
    # Use the complementary error function approximation
    x = math.sqrt(chi2 / 2)
    p = math.erfc(x / math.sqrt(2))
    return min(1.0, max(0.0, p))
