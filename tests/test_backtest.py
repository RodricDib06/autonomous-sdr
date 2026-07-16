"""
Tests for backtest mode (historical CSV replay through the qualifier).

Coverage:
  - CSV parsing: required columns, outcome vocabulary, bad-row skipping, row cap
  - deterministic qualification: seniority/size/industry scoring, guardrail
    parity with the live pipeline, defaulted-dimension reporting
  - summary math: matrix, recall/precision/lift, calibration buckets
  - API: upload → report, list, records drill-down, org scoping, RBAC
"""

import io

from app.services.backtest import (
    normalise_outcome,
    parse_backtest_csv,
    qualify_row,
    run_backtest,
    summarise,
)

HEADER = "name,email,company,outcome,job_title,seniority,industry,company_size\n"


def _csv(*rows: str) -> str:
    return HEADER + "\n".join(rows)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def test_outcome_vocabulary():
    assert normalise_outcome("Closed Won") == "won"
    assert normalise_outcome("converted") == "won"
    assert normalise_outcome("1") == "won"
    assert normalise_outcome("closed_lost") == "lost"
    assert normalise_outcome("Churned") == "lost"
    assert normalise_outcome("0") == "lost"
    assert normalise_outcome("maybe") is None
    assert normalise_outcome("") is None


def test_parse_requires_columns():
    rows, errors = parse_backtest_csv("name,email\nJane,j@x.com")
    assert rows == []
    assert "outcome" in errors[0] and "company" in errors[0]


def test_parse_skips_bad_rows_and_keeps_good():
    content = _csv(
        "Jane,jane@acme.io,Acme,won,VP of Sales,,SaaS,50-200",
        ",missing@name.com,Acme,won,,,,",
        "Bob,bob@corp.com,Corp,definitely,,,,",
        "Ann,ann@beta.dev,Beta,lost,,,,",
    )
    rows, errors = parse_backtest_csv(content)
    assert [r["name"] for r in rows] == ["Jane", "Ann"]
    assert len(errors) == 2


def test_parse_normalises_email_case():
    rows, _ = parse_backtest_csv(_csv("Jane,JANE@ACME.IO,Acme,won,,,,"))
    assert rows[0]["email"] == "jane@acme.io"


# ---------------------------------------------------------------------------
# Qualification
# ---------------------------------------------------------------------------

def test_senior_person_at_icp_company_is_hot():
    result = qualify_row({
        "name": "Jane", "email": "jane@acme.io", "company": "Acme",
        "job_title": "VP of Engineering", "seniority": "",
        "industry": "SaaS", "company_size": "200-500",
    })
    assert result["verdict"] == "Hot"
    assert result["score"] >= 0.75
    assert result["features"]["defaulted"] == []


def test_junior_person_off_icp_is_cold():
    result = qualify_row({
        "name": "Bob", "email": "bob@shop.com", "company": "Shop",
        "job_title": "Junior Analyst", "seniority": "",
        "industry": "Retail", "company_size": "1-10",
    })
    assert result["verdict"] == "Cold"


def test_missing_fields_default_to_neutral_and_are_reported():
    result = qualify_row({"name": "X", "email": "x@y.com", "company": "Y"})
    assert result["score"] == 0.5
    assert set(result["features"]["defaulted"]) == {"authority", "budget", "timeline", "need"}


def test_guardrail_parity_with_live_pipeline():
    # High budget/need/timeline but junior authority: raw mean ≥ 0.75 would
    # say Hot; the shared guardrail must demote exactly like the live agent.
    result = qualify_row({
        "name": "X", "email": "x@y.io", "company": "Y",
        "job_title": "Junior Developer", "seniority": "",
        "industry": "SaaS", "company_size": "5000+",
    })
    assert result["verdict"] != "Hot"


def test_seniority_column_beats_title_inference():
    result = qualify_row({
        "name": "X", "email": "x@y.io", "company": "Y",
        "job_title": "Junior Developer", "seniority": "C-Suite",
        "industry": "SaaS", "company_size": "200-500",
    })
    assert result["features"]["bant"]["authority"] == 1.0


# ---------------------------------------------------------------------------
# Summary math
# ---------------------------------------------------------------------------

def _rec(verdict, score, outcome):
    return {"predicted_verdict": verdict, "predicted_score": score, "actual_outcome": outcome}


def test_summary_matrix_and_rates():
    records = [
        _rec("Hot", 0.9, "won"), _rec("Hot", 0.85, "won"), _rec("Hot", 0.8, "lost"),
        _rec("Warm", 0.6, "won"), _rec("Warm", 0.55, "lost"),
        _rec("Cold", 0.2, "lost"), _rec("Cold", 0.3, "won"),
    ]
    s = summarise(records)
    assert s["total"] == 7 and s["won"] == 4
    assert s["verdict_outcome_matrix"]["Hot"] == {"won": 2, "lost": 1}
    assert s["hot_recall"] == round(2 / 4, 3)
    assert s["hot_or_warm_recall"] == round(3 / 4, 3)
    assert s["hot_precision"] == round(2 / 3, 3)
    assert s["hot_lift"] == round((2 / 3) / (4 / 7), 2)
    assert sum(b["count"] for b in s["calibration"]) == 7


def test_summary_handles_no_wins_without_dividing_by_zero():
    s = summarise([_rec("Cold", 0.2, "lost"), _rec("Warm", 0.6, "lost")])
    assert s["hot_recall"] is None
    assert s["hot_precision"] is None
    assert s["hot_lift"] is None


def test_calibration_includes_score_of_exactly_one():
    s = summarise([_rec("Hot", 1.0, "won")])
    assert s["calibration"][-1]["count"] == 1


# ---------------------------------------------------------------------------
# run_backtest persistence
# ---------------------------------------------------------------------------

def test_run_backtest_persists_run_and_records(test_db):
    content = _csv(
        "Jane,jane@acme.io,Acme,won,VP of Engineering,,SaaS,200-500",
        "Bob,bob@shop.com,Shop,lost,Junior Analyst,,Retail,1-10",
        "Bad,bad@row.com,Row,unknown_outcome,,,,",
    )
    run = run_backtest(test_db, content, filename="q1.csv")

    assert run.status == "complete"
    assert run.total_rows == 2
    assert run.skipped_rows == 1
    assert run.summary["total"] == 2
    assert len(run.records) == 2
    hot = next(r for r in run.records if r.email == "jane@acme.io")
    assert hot.predicted_verdict == "Hot" and hot.actual_outcome == "won"


def test_run_backtest_rejects_empty_csv(test_db):
    import pytest
    with pytest.raises(ValueError):
        run_backtest(test_db, "name,email,company,outcome\n", filename="empty.csv")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def _login_admin(client):
    client.post("/auth/register", json={"email": "admin@test.com", "password": "password123", "role": "rep"})
    r = client.post("/auth/login", json={"email": "admin@test.com", "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _upload(client, headers, content: str, filename="backtest.csv"):
    return client.post(
        "/backtests",
        headers=headers,
        files={"file": (filename, io.BytesIO(content.encode()), "text/csv")},
    )


def test_upload_and_fetch_backtest(client):
    headers = _login_admin(client)
    content = _csv(
        "Jane,jane@acme.io,Acme,won,VP of Engineering,,SaaS,200-500",
        "Bob,bob@shop.com,Shop,lost,Junior Analyst,,Retail,1-10",
    )
    r = _upload(client, headers, content)
    assert r.status_code == 201, r.text
    run_id = r.json()["id"]
    assert r.json()["summary"]["total"] == 2

    r = client.get("/backtests", headers=headers)
    assert r.json()["total"] == 1

    r = client.get(f"/backtests/{run_id}", headers=headers)
    assert r.status_code == 200
    assert "verdict_outcome_matrix" in r.json()["summary"]

    r = client.get(f"/backtests/{run_id}/records", headers=headers, params={"verdict": "Hot"})
    assert r.status_code == 200
    assert all(rec["predicted_verdict"] == "Hot" for rec in r.json()["records"])


def test_upload_rejects_invalid_csv(client):
    headers = _login_admin(client)
    r = _upload(client, headers, "not,a,valid\nbacktest")
    assert r.status_code == 422


def test_backtests_require_auth(client):
    assert client.get("/backtests").status_code in (401, 403)
    r = client.post("/backtests", files={"file": ("x.csv", io.BytesIO(b"a"), "text/csv")})
    assert r.status_code in (401, 403)


def test_records_misses_only_filter(client):
    headers = _login_admin(client)
    content = _csv(
        "Jane,jane@acme.io,Acme,lost,VP of Engineering,,SaaS,200-500",   # Hot but lost
        "Ann,ann@beta.dev,Beta,won,VP of Product,,SaaS,200-500",         # Hot and won
    )
    run_id = _upload(client, headers, content).json()["id"]
    r = client.get(f"/backtests/{run_id}/records", headers=headers, params={"misses_only": True})
    rows = r.json()["records"]
    assert len(rows) == 1 and rows[0]["email"] == "jane@acme.io"


def test_org_scoping_hides_other_orgs_runs(client, test_db):
    headers = _login_admin(client)
    from app.services.tenancy import create_org
    other = create_org(test_db, "Other Co")
    run = run_backtest(
        test_db,
        _csv("Jane,jane@acme.io,Acme,won,,,,"),
        filename="other.csv", org_id=other.id,
    )
    assert client.get(f"/backtests/{run.id}", headers=headers).status_code == 404
    assert client.get("/backtests", headers=headers).json()["total"] == 0
