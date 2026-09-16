"""
Record the real API's response shapes so the frontend mocks can be checked
against them.

Why this exists: the MSW handlers are hand-written, and nothing tied them to
what the API actually returns. They drifted — `avg_quality_score` in the mock
versus `average_quality_score` on the wire, and a `quality_distribution` whose
keys carried score ranges the mock omitted. Every test passed while the
Dashboard and Analytics pages rendered 0 in production. A high test count
measured nothing, because the fixture and the server disagreed.

This captures *key names only* — never values — for a curated set of endpoints
the UI destructures, and writes them to a JSON file the frontend contract test
asserts against. Run it whenever a response shape changes on purpose:

    python scripts/capture_api_contracts.py --base-url http://localhost:8000 \\
        --email admin@example.com --password ...
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urljoin

import requests

OUT = Path(__file__).resolve().parent.parent / "frontend/src/__tests__/mocks/api-contracts.json"

# Endpoints whose exact shape the UI depends on. Parameterised paths are
# resolved at capture time from live data, so the recorded shape is real.
ENDPOINTS: list[tuple[str, str]] = [
    ("GET", "/health"),
    ("GET", "/leads/stats"),
    ("GET", "/leads/quality-report"),
    ("GET", "/leads/hot"),
    ("GET", "/leads/trend"),
    ("GET", "/leads/import-history"),
    ("GET", "/outreach/stats"),
    ("GET", "/outreach/approvals"),
    ("GET", "/outreach/autonomy"),
    ("GET", "/analytics/funnel"),
    ("GET", "/analytics/roi"),
    ("GET", "/campaigns"),
    ("GET", "/backtests"),
    ("GET", "/ab-tests/results"),
    ("GET", "/optimization/weights"),
    ("GET", "/prospecting/runs"),
    ("GET", "/icp"),
]


def shape(value, depth: int = 0):
    """Key names only — structure without content, so nothing sensitive lands in git."""
    if depth > 3:
        return "..."
    if isinstance(value, dict):
        return {k: shape(v, depth + 1) for k, v in sorted(value.items())}
    if isinstance(value, list):
        # A list's contract is its element shape; an empty list constrains nothing.
        return [shape(value[0], depth + 1)] if value else []
    return type(value).__name__


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    args = ap.parse_args()

    login = requests.post(
        urljoin(args.base_url, "/auth/login"),
        json={"email": args.email, "password": args.password},
        timeout=120,
    )
    if login.status_code != 200:
        print(f"login failed: {login.status_code} {login.text[:200]}")
        return 1
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    contracts: dict[str, dict] = {}
    for method, path in ENDPOINTS:
        try:
            r = requests.request(method, urljoin(args.base_url, path), headers=headers, timeout=120)
        except Exception as e:
            print(f"  {path}: request failed ({e}) — skipped")
            continue
        if r.status_code != 200:
            print(f"  {path}: HTTP {r.status_code} — skipped")
            continue
        try:
            body = r.json()
        except ValueError:
            print(f"  {path}: non-JSON — skipped")
            continue
        contracts[f"{method} {path}"] = shape(body)
        print(f"  {path}: captured")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(contracts, indent=2, sort_keys=True) + "\n")
    print(f"\nwrote {len(contracts)} contracts -> {OUT.relative_to(Path.cwd())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
