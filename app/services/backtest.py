"""
Backtest mode — replay a historical CRM export through the qualifier.

The buyer uploads last quarter's leads with known outcomes (won/lost); every
row is scored by the same deterministic BANT heuristics and guardrails the
live pipeline enforces, and the summary shows how the verdicts line up with
what actually closed: "the agent flagged 80% of your closed-won deals as
Hot" is an argument made with the buyer's own data.

Scoring is deliberately LLM-free: a backtest must be reproducible (same CSV
in, same numbers out) and free to run on 10 000 rows. It uses only fields
present in the CSV — missing dimensions default to a neutral 0.5 and are
reported in each record's `features.defaulted` list, never guessed.

CSV columns:
  required  name, email, company, outcome (won/closed_won/converted/1 …
            vs lost/closed_lost/churned/0 …)
  optional  job_title, seniority, industry, company_size, revenue
"""

from __future__ import annotations

import csv
import io
import logging
import re
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.agents.analysis_agent import _apply_bant_guardrails
from app.config import settings
from app.database.models import BacktestRecord, BacktestRun
from app.services.icp_service import evaluate_icp, get_icp_config, parse_company_size
from app.utils.time import utcnow

log = logging.getLogger(__name__)

MAX_ROWS = 20_000

REQUIRED_FIELDS = {"name", "email", "company", "outcome"}
OPTIONAL_FIELDS = ("job_title", "seniority", "industry", "company_size", "revenue")

_WON_VALUES = {"won", "closed_won", "closed-won", "converted", "win", "customer", "yes", "true", "1"}
_LOST_VALUES = {"lost", "closed_lost", "closed-lost", "churned", "no_decision", "no", "false", "0"}

# Job-title keywords → seniority bucket, checked in order (most senior first)
_TITLE_SENIORITY = (
    (re.compile(r"\b(ceo|cto|coo|cfo|cpo|ciso|cro|cmo|chief|founder|owner|president)\b", re.I), "C-Suite"),
    (re.compile(r"\b(vp|vice\s+president)\b", re.I), "VP"),
    (re.compile(r"\b(director|head\s+of)\b", re.I), "Director"),
    (re.compile(r"\b(manager|lead)\b", re.I), "Manager"),
    (re.compile(r"\b(senior|staff|principal)\b", re.I), "Senior"),
    (re.compile(r"\b(junior|associate|intern)\b", re.I), "Junior"),
)

_SENIORITY_AUTHORITY = {
    "c-suite": 1.0, "c-level": 1.0, "founder": 1.0,
    "vp": 0.85,
    "director": 0.7,
    "manager": 0.5,
    "senior": 0.35,
    "mid-level": 0.25,
    "junior": 0.15,
}

_NEUTRAL = 0.5
_CALIBRATION_BUCKETS = 5


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

def normalise_outcome(raw: str) -> str | None:
    """Map CRM outcome vocabulary to won/lost; None when unrecognised."""
    value = (raw or "").strip().lower().replace(" ", "_")
    if value in _WON_VALUES:
        return "won"
    if value in _LOST_VALUES:
        return "lost"
    return None


def parse_backtest_csv(csv_content: str) -> tuple[list[dict], list[str]]:
    """
    Parse and validate the upload. Returns (rows, errors); rows that fail
    validation are reported in errors and skipped, they never abort the run.
    """
    rows: list[dict] = []
    errors: list[str] = []

    reader = csv.DictReader(io.StringIO(csv_content))
    if not reader.fieldnames:
        return rows, ["CSV file is empty"]

    fieldnames = {(f or "").strip().lower() for f in reader.fieldnames}
    missing = REQUIRED_FIELDS - fieldnames
    if missing:
        return rows, [f"Missing required columns: {', '.join(sorted(missing))}"]

    for row_num, raw in enumerate(reader, start=2):
        if len(rows) >= MAX_ROWS:
            errors.append(f"Row limit of {MAX_ROWS} reached — remaining rows ignored")
            break

        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        if not (row.get("name") and row.get("email") and row.get("company")):
            errors.append(f"Row {row_num}: name, email, and company are required")
            continue

        outcome = normalise_outcome(row.get("outcome", ""))
        if outcome is None:
            errors.append(f"Row {row_num}: unrecognised outcome '{row.get('outcome', '')}'")
            continue

        rows.append({
            "row_number": row_num,
            "name": row["name"],
            "email": row["email"].lower(),
            "company": row["company"],
            "outcome": outcome,
            **{f: row.get(f, "") for f in OPTIONAL_FIELDS},
        })

    return rows, errors


# ---------------------------------------------------------------------------
# Deterministic qualification (mirrors the live pipeline's guardrails)
# ---------------------------------------------------------------------------

def _seniority_from_title(job_title: str) -> str | None:
    for pattern, seniority in _TITLE_SENIORITY:
        if pattern.search(job_title):
            return seniority
    return None


def _score_budget(headcount: int | None) -> float:
    if headcount is None:
        return _NEUTRAL
    if headcount <= 10:
        return 0.2
    if headcount <= 50:
        return 0.4
    if headcount <= 200:
        return 0.6
    if headcount <= 500:
        return 0.75
    return 0.9


def _score_timeline(headcount: int | None) -> float:
    # Smaller companies decide faster — the inverse of budget capacity
    if headcount is None:
        return _NEUTRAL
    if headcount <= 50:
        return 0.8
    if headcount <= 200:
        return 0.65
    if headcount <= 500:
        return 0.5
    return 0.35


def _score_need(industry: str, target_industries: list[str]) -> float:
    if not industry:
        return _NEUTRAL
    industry_l = industry.lower()
    targets = [t.lower() for t in target_industries]
    if industry_l in targets:
        return 0.9
    if any(t in industry_l or industry_l in t for t in targets):
        return 0.7
    if any(kw in industry_l for kw in ("tech", "software", "saas", "it ", "cloud", "data")):
        return 0.5
    return 0.3


def qualify_row(row: dict, icp_config=None) -> dict:
    """
    Score one historical lead with the same BANT dimensions, thresholds, and
    guardrails as the live analysis stage. Returns verdict, score, per-
    dimension breakdown, and which dimensions ran on defaults.
    """
    defaulted: list[str] = []

    seniority = row.get("seniority", "")
    if not seniority and row.get("job_title"):
        seniority = _seniority_from_title(row["job_title"]) or ""
    authority = _SENIORITY_AUTHORITY.get(seniority.strip().lower())
    if authority is None:
        authority = _NEUTRAL
        defaulted.append("authority")

    headcount = parse_company_size(row.get("company_size"))
    budget = _score_budget(headcount)
    timeline = _score_timeline(headcount)
    if headcount is None:
        defaulted.extend(["budget", "timeline"])

    target_industries = list(icp_config.industries) if icp_config is not None and icp_config.industries else settings.icp_industries
    need = _score_need(row.get("industry", ""), target_industries)
    if not row.get("industry"):
        defaulted.append("need")

    bant = {
        "budget": round(budget, 3),
        "authority": round(authority, 3),
        "need": round(need, 3),
        "timeline": round(timeline, 3),
    }
    overall = round(sum(bant.values()) / 4, 3)

    if overall >= 0.75:
        verdict = "Hot"
    elif overall >= 0.5:
        verdict = "Warm"
    else:
        verdict = "Cold"
    verdict, flag = _apply_bant_guardrails(verdict, bant, overall)

    icp_result = evaluate_icp(
        SimpleNamespace(
            industry=row.get("industry") or None,
            seniority=seniority or None,
            company_size=row.get("company_size") or None,
        ),
        icp_config,
    )

    reasoning_bits = [f"BANT {overall:.2f} ({', '.join(f'{k}={v:.2f}' for k, v in bant.items())})"]
    if defaulted:
        reasoning_bits.append(f"defaulted: {', '.join(sorted(set(defaulted)))}")
    if flag:
        reasoning_bits.append(f"guardrail: {flag}")

    return {
        "verdict": verdict,
        "score": overall,
        "icp_match": icp_result["overall"],
        "features": {"bant": bant, "defaulted": sorted(set(defaulted)),
                     "guardrail_flag": flag or None, "headcount": headcount,
                     "seniority": seniority or None},
        "reasoning": "; ".join(reasoning_bits),
    }


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _safe_rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 3) if denominator else None


def summarise(records: list[dict]) -> dict:
    """
    Calibration summary over scored rows. `records` items need:
    predicted_verdict, predicted_score, actual_outcome.
    """
    total = len(records)
    won = sum(1 for r in records if r["actual_outcome"] == "won")
    base_win_rate = _safe_rate(won, total)

    matrix = {v: {"won": 0, "lost": 0} for v in ("Hot", "Warm", "Cold")}
    for r in records:
        matrix[r["predicted_verdict"]][r["actual_outcome"]] += 1

    hot = matrix["Hot"]
    warm = matrix["Warm"]
    hot_total = hot["won"] + hot["lost"]
    hot_warm_won = hot["won"] + warm["won"]
    hot_win_rate = _safe_rate(hot["won"], hot_total)

    buckets = []
    width = 1.0 / _CALIBRATION_BUCKETS
    for i in range(_CALIBRATION_BUCKETS):
        lo, hi = round(i * width, 2), round((i + 1) * width, 2)
        # Final bucket is closed on the right so score 1.0 lands somewhere
        in_bucket = [
            r for r in records
            if lo <= r["predicted_score"] < hi or (i == _CALIBRATION_BUCKETS - 1 and r["predicted_score"] == hi)
        ]
        bucket_won = sum(1 for r in in_bucket if r["actual_outcome"] == "won")
        buckets.append({
            "range": [lo, hi],
            "count": len(in_bucket),
            "mean_predicted_score": round(sum(r["predicted_score"] for r in in_bucket) / len(in_bucket), 3) if in_bucket else None,
            "actual_win_rate": _safe_rate(bucket_won, len(in_bucket)),
        })

    return {
        "total": total,
        "won": won,
        "lost": total - won,
        "base_win_rate": base_win_rate,
        "verdict_outcome_matrix": matrix,
        # "Of your closed-won deals, what share did the agent flag Hot?"
        "hot_recall": _safe_rate(hot["won"], won),
        "hot_or_warm_recall": _safe_rate(hot_warm_won, won),
        # "Of the leads it called Hot, what share actually closed?"
        "hot_precision": hot_win_rate,
        # Win rate among Hot verdicts vs the overall base rate
        "hot_lift": round(hot_win_rate / base_win_rate, 2) if hot_win_rate is not None and base_win_rate else None,
        "calibration": buckets,
    }


# ---------------------------------------------------------------------------
# Run orchestration
# ---------------------------------------------------------------------------

def run_backtest(
    db: Session,
    csv_content: str,
    filename: str,
    org_id: str | None = None,
    created_by_id: str | None = None,
) -> BacktestRun:
    """
    Parse, score, and persist a complete backtest. Raises ValueError when the
    CSV yields no scoreable rows; per-row problems are recorded on the run.
    """
    rows, errors = parse_backtest_csv(csv_content)
    if not rows:
        raise ValueError("; ".join(errors) or "No valid rows in CSV")

    icp_config = get_icp_config(db, org_id=org_id)

    run = BacktestRun(
        org_id=org_id,
        filename=filename,
        created_by_id=created_by_id,
        total_rows=len(rows),
        skipped_rows=len(errors),
        error_message="\n".join(errors[:50]) or None,
        created_at=utcnow(),
    )
    db.add(run)
    db.flush()

    scored: list[dict] = []
    for row in rows:
        result = qualify_row(row, icp_config)
        db.add(BacktestRecord(
            run_id=run.id,
            row_number=row["row_number"],
            name=row["name"],
            email=row["email"],
            company=row["company"],
            actual_outcome=row["outcome"],
            predicted_verdict=result["verdict"],
            predicted_score=result["score"],
            icp_match=result["icp_match"],
            features=result["features"],
            reasoning=result["reasoning"],
        ))
        scored.append({
            "predicted_verdict": result["verdict"],
            "predicted_score": result["score"],
            "actual_outcome": row["outcome"],
        })

    run.summary = summarise(scored)
    run.status = "complete"
    db.commit()
    db.refresh(run)

    log.info(
        f"[backtest] {filename}: {len(rows)} rows scored "
        f"(hot_recall={run.summary.get('hot_recall')}, hot_lift={run.summary.get('hot_lift')})"
    )
    return run
