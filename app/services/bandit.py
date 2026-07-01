"""
Multi-Armed Bandit: Thompson Sampling for A/B outreach variant selection.

Why Thompson Sampling over even-split or chi-square:
  - Even-split wastes traffic on the losing variant even when evidence is clear
  - Chi-square is retrospective: you declare a winner after significance, not during
  - Thompson Sampling is online: it routes more traffic to the better variant as
    evidence accumulates, while never fully stopping exploration

How it works:
  Each variant maintains a Beta(α, β) distribution over its true conversion rate:
    α = conversions + 1      (Laplace smoothing — non-zero prior)
    β = non_conversions + 1

  At routing time, sample θ_i ~ Beta(α_i, β_i) for each variant.
  Route to the variant whose sample is highest.

  When both variants have zero data: Beta(1,1) = Uniform[0,1], so each gets
  50% traffic — identical to even-split. As conversions accumulate, the
  distribution concentrates around the true rate and routing tilts accordingly.

Chi-square in ab_testing.py is kept as the "promote winner" gate — it declares
a winner and deactivates other sequences. Thompson sampling is purely a routing
decision; promotion is a separate (permanent) action.
"""

import random
import logging

log = logging.getLogger(__name__)


def thompson_select(variants: list[dict]) -> dict:
    """
    Select a variant using Thompson Sampling.

    Each dict in `variants` must have:
      id          : str   — sequence identifier
      emails_sent : int   — total emails sent for this variant
      conversions : int   — confirmed conversions (meetings booked or CRM converted)

    Returns the chosen variant dict with an additional 'thompson_sample' key
    showing the sampled conversion-rate estimate used for selection.
    """
    if not variants:
        raise ValueError("thompson_select called with no variants")

    if len(variants) == 1:
        return {**variants[0], "thompson_sample": 1.0}

    samples = []
    for v in variants:
        sent = max(0, v.get("emails_sent") or 0)
        conversions = max(0, v.get("conversions") or 0)
        non_conversions = max(0, sent - conversions)

        alpha = conversions + 1.0
        beta = non_conversions + 1.0
        sample = random.betavariate(alpha, beta)

        log.debug(
            f"[bandit] variant={v.get('ab_variant', v['id'][:8])} "
            f"α={alpha:.0f} β={beta:.0f} θ={sample:.4f}"
        )
        samples.append((sample, v))

    best_sample, best_variant = max(samples, key=lambda x: x[0])
    return {**best_variant, "thompson_sample": best_sample}


def get_bandit_state(variants: list[dict], n_simulations: int = 1000) -> list[dict]:
    """
    Return the Beta distribution state and estimated win probability for each variant.
    Uses Monte Carlo simulation over n_simulations to estimate P(variant_i wins).

    Each input dict must have: id, emails_sent, conversions, ab_variant (optional).
    """
    if not variants:
        return []

    # Build (alpha, beta) per variant
    params = []
    for v in variants:
        sent = max(0, v.get("emails_sent") or 0)
        conversions = max(0, v.get("conversions") or 0)
        non_conversions = max(0, sent - conversions)
        params.append((conversions + 1.0, non_conversions + 1.0))

    # Monte Carlo win-probability estimate
    win_counts = [0] * len(variants)
    for _ in range(n_simulations):
        samples = [random.betavariate(a, b) for a, b in params]
        winner_idx = samples.index(max(samples))
        win_counts[winner_idx] += 1

    results = []
    for i, v in enumerate(variants):
        sent = max(0, v.get("emails_sent") or 0)
        conversions = max(0, v.get("conversions") or 0)
        alpha, beta = params[i]
        results.append({
            **v,
            "bandit_alpha": alpha,
            "bandit_beta": beta,
            "bandit_mean": alpha / (alpha + beta),
            "bandit_win_probability": round(win_counts[i] / n_simulations, 4),
            "estimated_conversion_rate": round(conversions / sent, 4) if sent > 0 else None,
        })

    return results
