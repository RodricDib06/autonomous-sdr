# Session handoff — 2026-09-16

Working notes for picking this back up. Not part of the product docs; delete
once the open items are done.

## Live deployment

| Thing | Where |
|---|---|
| Frontend | https://autonomoussdr-web.onrender.com |
| API | https://autonomoussdr-api.onrender.com |
| Public login | `demo@autonomoussdr.com` / `demo` — **read-only** |
| Admin login | `admin@autonomoussdr.com` / `AutonomousDemo2026!` — full access, keep private |
| Postgres | Neon project `weathered-hat-55408437`, branch `production` (never expires) |
| Redis | Render Key Value `autonomoussdr-redis` (free, in-memory only) |
| Render services | `srv-dal0f8uk1f9s73d8so0g` (api), `srv-dal0fktbedkc73aq3f3g` (web) |

Render does **not** auto-deploy on push (no GitHub webhook — it pulls the public
repo). Trigger manually in the dashboard, or:

```
curl -X POST -H "Authorization: Bearer $RENDER_API_KEY" \
  -H "Content-Type: application/json" -d '{"clearCache":"do_not_clear"}' \
  https://api.render.com/v1/services/srv-dal0f8uk1f9s73d8so0g/deploys
```

Free tier sleeps after 15 min idle; first request takes ~60s. The login page
pre-warms the API and shows a "waking the server" hint after 4s.

## DO THIS FIRST

**Rotate three credentials.** All were pasted into a chat transcript:
Render API key, Neon API key, Groq API key. Rotating Groq means updating
`GROQ_MODEL`'s sibling `GROQ_API_KEY` on the api service.

## What changed this session

All pushed to `main`, all deployed.

- `main.py` split: **3,557 → 1,022 lines**. Six routers extracted (leads,
  analytics, tracking, config, icp, experiments). Verified no route lost by
  diffing the local route table against the live OpenAPI.
- **`GET /leads/cooling` was returning 404 in production** — registered ~1,300
  lines below `GET /leads/{lead_id}`, so the catch-all ate it. The Dashboard
  queries it. Fixed, plus `tests/test_route_registration.py` now fails if any
  concrete route is shadowed.
- **Agents ignored `AI_PROVIDER`** — both built `OllamaClient()` directly, so
  production dialled localhost:11434, the validator failed on every lead, and
  leads completed with no verdict. Now go through `get_ai_client()` (which also
  restores per-call cost telemetry). Guarded by `tests/test_ai_provider_wiring.py`.
- **Groq's llama-3.x models are decommissioned.** Default is now
  `openai/gpt-oss-120b`. Check `GET https://api.groq.com/openai/v1/models`
  before changing it.
- Three test-harness blind spots closed (see below).
- Read-only demo account created and published.

Verified live after all of it: a real lead runs orchestrator → enrichment →
analysis → validator and returns a verdict (Warm, 0.92 confidence).

## Test harness

`982 → 1,009 tests` (506 backend, 503 frontend). Three blind spots that had
each let a real bug ship:

1. **Mock drift.** MSW handlers disagreed with the API (`avg_quality_score` vs
   `average_quality_score`), so the Dashboard rendered 0 while tests passed.
   `scripts/capture_api_contracts.py` records real response shapes from a
   running server into `frontend/src/__tests__/mocks/api-contracts.json`, and
   a contract test asserts the mocks match. Re-run it whenever a response shape
   changes on purpose:
   ```
   python scripts/capture_api_contracts.py --base-url https://autonomoussdr-api.onrender.com \
     --email admin@autonomoussdr.com --password 'AutonomousDemo2026!'
   ```
2. **Toast host.** `<Toaster />` lived in `Layout`, which wraps only
   authenticated routes, so login errors were unrenderable — while the test
   wrapper mounted its own and hid it. Now at the App root.
3. **Suppressed navigation.** `setup.ts` filtered out
   "Not implemented: navigation", which is how the 401 interceptor's page
   reload stayed invisible. Filter removed; `navigation-guard.ts` records
   attempts so tests assert on them.

## Open items

Roughly highest value first.

- [ ] **Rotate the three API keys** (above).
- [ ] **Record the 3-minute demo video** — `docs/demo-video-storyboard.md` is
      written and every scene now has data behind it. A hiring manager watches
      three minutes; they don't clone repos.
- [ ] **Write the LinkedIn post.** Draft and guidance are in the chat history;
      lead with the trust/receipts angle, not "I built an AI SDR". Claim no
      traction — there are no users and no real outreach sent.
- [ ] `docs/demo-video-storyboard.md` has a stray indent on its H1 (from the
      editor) that breaks the heading — one-character fix, left alone
      deliberately since it wasn't mine.
- [ ] Re-add `preDeployCommand: python scripts/render_predeploy.py` to the api
      service. It was left off to de-risk the first deploy, so **migrations no
      longer run automatically** — run them manually before any deploy that
      adds one.
- [ ] Analytics endpoints still aren't org-scoped (own debt register) — a real
      multi-tenancy hole.
- [ ] Frontend bundle is 1.1 MB; no route-level code splitting.
- [ ] Husky v10 deprecation warning on every commit.
- [ ] OAuth mailbox flows are unit-tested against mocks only — do one real
      round trip before demoing that flow.
- [ ] Free Key Value is in-memory, so queued leads are lost on restart. The
      scheduler re-queues stale pending leads every 5 min, so it self-heals.

## Re-seeding the demo data

Seeders are idempotent. Against the live database:

```
export DATABASE_URL="<neon connection string>"
python scripts/seed_demo_data.py && python scripts/seed_demo_flagship.py
```

Render's free tier has no shell, so this has to run locally against the remote
URL. `seed_demo_flagship.py` adopts orphaned leads into the default org first —
without that, campaign metrics read 0 because campaigns are org-scoped and the
base seeder predates multi-tenancy.
