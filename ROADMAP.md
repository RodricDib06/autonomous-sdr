# ROADMAP — From Autonomous Workflow to Autonomous Employee

> **How to use this file:** this is the working plan for the next era of AutonomousSDR.
> Each item has a checkbox. When a work session completes something, tick it and add
> the commit hash. When priorities change, edit the plan — this file is the source of
> truth, not the chat history. Statuses: `[ ]` todo · `[~]` in progress · `[x]` done.
>
> Baseline: commit `9dc8de8` (2026-07-16) — provenance-grounded emails, backtest mode,
> email verification + bounce handling, OAuth mailboxes, full dashboard UI.
> 419 backend + 461 frontend tests. Migration chain 0001→0012.

---

## The diagnosis this plan fixes

The platform today is an **autonomous workflow**: given a lead, everything downstream
runs itself (qualification, outreach, follow-ups, replies, bounces, re-qualification,
A/B routing, BANT self-tuning). What it is *not yet* is an **autonomous seller**.
Three structural gaps:

| # | Gap | Consequence | Fixed by |
|---|-----|-------------|----------|
| 1 | **It reacts, never originates** — pipeline starts only from webhooks/CSV a human provides | Empty pipeline = idle agent. The top of the funnel doesn't exist | Phase 7 |
| 2 | **It has no goal** — cron jobs execute, nothing *tries* to achieve anything, no replanning when failing | No agency; can't answer "are we on track?" or change strategy | Phase 6 |
| 3 | **Learning is narrow** — BANT weights + bandit adapt; the *messaging* never does | It gets more calibrated, not smarter. Objections in replies are wasted data | Phase 8 |

Phase 9 is the commercial track (what actually makes companies buy), Phase 10 is
enterprise hardening (deliberately deferred), and the last section is the debt register.

**Recommended order: 6 → 7 → 8 → 9 (9 runs partly in parallel — it's mostly founder
work, not code).** Each phase is shippable alone; 7 and 8 both plug into 6.

---

## Phase 6 — Campaign Manager Agent (goal-directed autonomy) 🚩 FLAGSHIP

**One sentence:** an agent that is handed a quota and constraints, continuously
plans against them using the primitives that already exist, and explains itself —
extending the autonomy dial from *emails* to *strategy*.

**Why first:** highest ratio of "genuinely advanced" to "buildable on what exists".
Sequences CRUD, the Thompson bandit, analytics, booking records, the approval queue,
and org settings are all already built — this phase composes them under a planner.

### 6.1 Data model (new alembic migration 0013)

- [ ] `Campaign` table: `id, org_id, name, goal_type` (`meetings` | `replies` | `qualified_leads`),
      `goal_target` (int), `period_start`, `period_end`, `status` (`active|paused|completed`),
      `constraints` JSONB — `{max_bounce_rate, max_daily_sends, max_monthly_llm_usd, segments: [{industry?, seniority?, company_size_min/max?}]}`,
      `created_by_id`, `created_at`
- [ ] `CampaignPlan` table: `id, campaign_id (FK, index), version (int), status`
      (`pending_approval|approved|rejected|active|superseded`), `generated_at`,
      `diagnosis` (Text — the agent's read of the situation), `actions` JSONB (see 6.3),
      `metrics_snapshot` JSONB (inputs the plan was based on — auditability),
      `report_md` (Text, nullable — weekly report), `approved_by_id`, `approved_at`
- [ ] `CampaignActionLog` table: `id, plan_id, action_type, payload JSONB, executed_at,
      success bool, error_message` — append-only record of what the agent actually did
- [ ] Leads gain nothing — campaigns select leads via segment filters, not FK
      (keeps ingest decoupled). A helper resolves segment → SQLAlchemy filter.

### 6.2 Metrics provider — `app/services/campaign_metrics.py` (pure SQL, no LLM)

- [ ] `campaign_progress(db, campaign)` → meetings booked (BookingRequest confirmed),
      replies, sends, bounce rate, spend (LLMCall costs), per segment and total,
      within the campaign period
- [ ] `pace(db, campaign)` → `{expected_by_now, actual, pace_ratio, projected_end_total}`
      (linear pace over the period; weekends excluded to match send guardrails)
- [ ] `sequence_performance_by_segment(db, campaign)` → per (sequence, segment):
      sent/opened/replied/bounced/meetings — reuses OutreachEmail + ABTestResult
- [ ] Unit tests: pace math edge cases (period not started, zero target, over-target),
      segment filter correctness, empty data

### 6.3 The planner — `app/agents/campaign_agent.py`

The loop: **observe → diagnose → propose → (approve) → execute → report.**

- [ ] Action vocabulary (pydantic-validated, the LLM can ONLY emit these):
  - `pause_sequence {sequence_id, reason}`
  - `resume_sequence {sequence_id, reason}`
  - `create_variant {based_on_sequence_id, angle, draft_steps[]}` — agent drafts a
    new sequence via LLM and registers it in the bandit (is_active, org-scoped)
  - `reallocate {sequence_id, bandit_prior_boost}` — seeds Thompson priors
  - `adjust_daily_target {value}` — within `constraints.max_daily_sends`, never above
  - `request_prospecting {segment, count}` — no-op stub until Phase 7, then live
  - `escalate {severity, message}` — Slack + dashboard notification, no side effects
- [ ] `generate_plan(db, campaign)` — prompt = goal + constraints + metrics snapshot +
      last plan's outcome; returns diagnosis + action list. **Hard rules enforced in
      code, not prompt:** actions violating constraints are rejected at validation;
      malformed LLM output falls back to a deterministic conservative plan
      (`escalate` + no changes) — the agent must never fail open
- [ ] `execute_plan(db, plan)` — deterministic executor; each action logged to
      `CampaignActionLog`; idempotent (re-running a plan skips executed actions)
- [ ] Autonomy dial extension: org setting `campaign_autonomy` (`approve` | `auto`).
      `approve` = plans wait in a queue like emails do; `auto` = execute immediately.
      Default `approve` — strategy changes deserve a human until trusted
- [ ] Scheduler job (daily, Redis-locked like the other 11 jobs): for each active
      campaign, refresh metrics, generate plan **only if** pace_ratio drifted > 15%
      since last plan or 7 days elapsed — no plan spam
- [ ] Weekly report: LLM writes `report_md` from the week's ActionLog + metrics —
      "what I did, what I learned, what I'm changing" — stored on the plan,
      pushed to Slack if configured

### 6.4 API — `app/routers/campaigns.py`

- [ ] `POST /campaigns` (manager), `GET /campaigns`, `GET /campaigns/{id}`
      (progress + pace + active plan), `PUT /campaigns/{id}` (pause/edit),
      org-scoped like backtests
- [ ] `GET /campaigns/{id}/plans` (history), `POST /campaigns/{id}/plans/{pid}/approve`,
      `.../reject {reason}` — mirrors the email approval endpoints
- [ ] `POST /campaigns/{id}/replan` — manual "think again now" trigger
- [ ] `GET /campaigns/{id}/report` — latest report_md

### 6.5 UI — new `Campaigns` page (sidebar: Target/Flag icon, after Approvals)

- [ ] Campaign card: goal progress hero (actual vs pace line — recharts, one axis,
      validate any new palette colors with the dataviz validator before use),
      days remaining, bounce-rate + budget meters
- [ ] Plan review card: diagnosis text + action list rendered as human-readable
      diffs ("Pause 'Value-led 3-Step' — 0.4% reply rate in fintech segment"),
      Approve / Reject buttons; approved plans show execution status per action
- [ ] Weekly report rendered as markdown
- [ ] Create-campaign dialog: goal, period, constraints, segment builder
      (reuse ICP-style selectors)
- [ ] MSW handlers + integration tests (creation, plan approval flow, pace hero,
      constraint display)

### 6.6 Tests (backend)

- [ ] Pace + metrics math (6.2)
- [ ] Planner with mocked LLM: valid plan accepted; constraint-violating action
      rejected; garbage LLM output → conservative fallback plan
- [ ] Executor: each action type, idempotency, ActionLog written
- [ ] Autonomy: `approve` mode never executes unapproved plans
- [ ] RBAC + org scoping on all endpoints

**Definition of done:** create a campaign with a meetings goal → seed demo data →
daily job produces a plan with a real diagnosis → approving it visibly pauses a
sequence and registers an agent-drafted variant in the bandit → weekly report reads
like something a manager would actually skim. Demo script: "I gave it a quota."

---

## Phase 7 — Autonomous Prospecting (originate, don't react)

**One sentence:** ICP + closed-won lookalikes → the agent builds its own lead lists
from a real data provider, and the campaign agent tops up its own pipeline when
it's behind on goal.

### 7.1 Provider layer — `app/services/prospecting/`

- [ ] `base.py` — `ProspectSource.search(criteria, limit) -> list[ProspectCandidate]`
      (name, email, company, title, industry, size, source, cost_estimate)
- [ ] `pdl.py` — People Data Labs **Person Search API** (the existing `enrichment/pdl.py`
      client is enrich-by-email; search is a different endpoint). Config: reuse
      `PDL_API_KEY`; add `PROSPECTING_PROVIDER` (`synthetic` default | `pdl`)
- [ ] `synthetic.py` — deterministic demo source (seeded from `data/company_domains.json`)
      so the whole flow demos with zero keys, consistent with the enrichment story
- [ ] Optional (nice-to-have): waterfall enrichment for sourced leads — chain
      synthetic → Hunter → PDL with per-field confidence, so sourced contacts get
      the best available data before scoring

### 7.2 The sourcing pipeline — `app/services/prospecting/service.py`

Order matters — this is the quality gate that keeps prospecting from poisoning the DB:

- [ ] 1. `search()` against provider with segment criteria (from ICP config or a
      campaign segment)
- [ ] 2. **Suppression check** (`is_suppressed`) — never source someone who opted out
- [ ] 3. **Dedup** (`DeduplicationService`) — skip existing leads
- [ ] 4. **Email verification** (`verify_email`) — reject undeliverable before insert;
      this is why Phase 6 of the previous era was built
- [ ] 5. **Scoring** — ICP evaluation + lookalike score against closed-won; rank,
      keep top N
- [ ] 6. Insert as leads with `source="prospecting:pdl"`, push to the normal pipeline
- [ ] `ProspectingRun` model (migration 0013 or 0014): criteria, provider, found,
      rejected {suppressed, duplicate, undeliverable, low_score}, accepted, cost_usd,
      campaign_id nullable, created_by — full audit of where leads came from
- [ ] Budget guardrails in config: `PROSPECTING_MAX_LEADS_PER_DAY`,
      `PROSPECTING_MAX_MONTHLY_COST_USD` — enforced in code, surfaced in UI

### 7.3 Triggers

- [ ] Manual: `POST /prospecting/runs {criteria | campaign_id, limit, dry_run}` —
      `dry_run=true` returns candidates without inserting (preview-before-import)
- [ ] Autonomous: implement the Phase 6 `request_prospecting` action — campaign agent
      calls it when projected pipeline coverage < configurable multiple of remaining goal
- [ ] `GET /prospecting/runs` + run detail (accepted/rejected breakdown)

### 7.4 UI

- [ ] "Source leads" panel (on the Campaigns page, or ICP page for standalone use):
      criteria form → dry-run preview table (with per-candidate ICP/lookalike score
      and verification status) → "Import N leads" confirm
- [ ] Run history with rejection breakdown (shows the quality gate working — this is
      a demo moment, not just plumbing)
- [ ] Tests: mocked provider; gate order (suppressed candidate never inserted even if
      verified); budget cap; dry-run inserts nothing

**Definition of done:** an empty org with an ICP config can click one button (or let
a campaign do it) and end up with verified, scored, deduped leads flowing through the
pipeline — no CSV, no webhook. The "it reacts" criticism is dead.

---

## Phase 8 — Reply Intelligence (the messaging learns)

**One sentence:** every inbound reply becomes structured data — classified, acted on,
aggregated — and the top objections per segment feed back into the campaign agent's
variant generation.

### 8.1 Classifier — `app/services/reply_classifier.py`

- [ ] Categories: `interested | objection | referral | wrong_person | not_now | auto_reply(ooo) | unsubscribe`
      with objection subtypes: `price | competitor | no_need | timing | trust`
- [ ] LLM classification with pydantic-validated output + **deterministic keyword
      fallback** (same philosophy as unsubscribe detection — the pipeline must work
      LLM-down); confidence score stored
- [ ] Storage: extend `Conversation` with `classification` JSONB
      (`{category, subtype, confidence, extracted: {referral_name?, referral_email?, resume_at?}}`)
      — migration alongside whatever phase ships first
- [ ] Wire into `reply_service.handle_reply` after the unsubscribe check (which stays
      first and keyword-based — compliance never waits on an LLM)

### 8.2 Actions per category

- [ ] `referral` → extract name/email → create new lead with `referred_by_lead_id`
      (column exists) → normal pipeline; original lead tagged
- [ ] `not_now` → schedule re-engagement at `resume_at` (or +90d default) — reuse the
      decay/reengagement infra (`reengagement_count` exists); cancel current cadence
- [ ] `wrong_person` → tag + trigger org-chart traversal (service exists, currently
      only fired on low-authority flags)
- [ ] `objection` → record; **no auto-argue** — the conversational agent may answer
      `interested` and simple questions, objections above a confidence threshold flag
      `needs_human` (field exists)
- [ ] `auto_reply` → do NOT cancel the cadence (today any reply cancels it — an OOO
      reply killing a sequence is a real bug this phase fixes)

### 8.3 Aggregation + feedback loop

- [ ] `GET /analytics/objections` — counts by subtype × segment × sequence, trending
- [ ] Feed top-3 objections per segment into the Phase 6 planner prompt so
      `create_variant` drafts copy that answers them — **this is the loop closing:**
      replies → objections → new messaging → bandit → results
- [ ] UI: classification chips in the Inbox (colored by category), objections panel
      on Analytics (bar chart — run the palette validator), referral chain already
      has UI via referred_by

### 8.4 Tests

- [ ] Keyword fallback determinism per category; OOO does not cancel cadence;
      referral creates linked lead; unsubscribe still wins over everything;
      aggregation math; needs_human flagging on objections

**Definition of done:** the Inbox shows *why* each reply matters at a glance; a
referral turns into a new qualified lead untouched; and a campaign plan cites a real
objection when proposing a variant.

---

## Phase 9 — Pilot Readiness (what actually makes companies buy)

> Code is ~40% of this phase. The rest is founder work. No feature substitutes for it.

### 9.1 Bidirectional HubSpot sync (build BEFORE first pilot call — it's asked in minute ten)

- [ ] HubSpot OAuth app (scopes: contacts, deals) — replaces bare API key; token
      storage pattern already exists (`oauth_mailbox.py` encrypt/refresh — generalize
      or copy)
- [ ] Inbound: webhook subscription (contact updated, deal stage changed) →
      `POST /ingest/hubspot-webhook` → update `conversion_status` — **this feeds the
      ML scorer, the optimization loop, and backtests with real outcomes**, which is
      the actual point, not checkbox parity
- [ ] `CrmSyncLog` table + conflict policy (CRM wins on ownership/stage fields;
      platform wins on scores)
- [ ] Settings UI: connect button (reuse OAuth connect pattern), sync status, log tail
- [ ] Tests: webhook signature validation, mapping, conflict policy

### 9.2 Go live (highest ROI item in the entire file — carried over twice already)

- [ ] Deploy on Railway (`railway.toml` exists): Postgres + Redis add-ons, stable
      `SECRET_KEY`, `APP_BASE_URL`, `alembic upgrade head` on boot, `AI_PROVIDER=groq`
      (free tier) or claude, `ENRICHMENT_PROVIDER=synthetic`
- [ ] Seeded demo org (`scripts/seed_demo_data.py`) + **read-only demo login** posted
      in the README ("click here, no signup")
- [ ] Deploy frontend (Vercel/Railway static) with `VITE_API_URL`
- [ ] Uptime check + error alerting (Slack webhook exists)

### 9.3 Evidence engine (founder work, zero code)

- [ ] Dogfood: run AutonomousSDR on AutonomousSDR's own outbound. Target sentence:
      *"It booked N meetings for itself."* Track in a doc; screenshot the ROI panel
- [ ] 3-minute demo video. Storyboard: lead lands → debate transcript → Fact Check
      panel (unverified claim caught) → approve with edit → **backtest on a real CSV**
      → campaign agent's weekly report → ROI panel. That order tells the trust story
- [ ] 3–5 design partners (free pilots), targeted: privacy-sensitive EU/B2B teams
      where "runs in your VPC" is disqualifying for 11x/Artisan. Trade: free use ↔
      testimonial + deliverability data
- [ ] One-pager: wedge positioning ("self-hosted AI SDR with receipts"), the three
      screenshots (Fact Check, backtest calibration, autonomy dial)
- [ ] Decision (deliberate, not default): open-core? Public repo + license + hosted
      tier is the n8n/Mattermost play and makes "self-hosted" credible; private repo
      makes it a demo. Decide and act — unique positioning that's private is a
      sentence in a README

### 9.4 Exit criteria for the phase

A stranger can: click a URL → poke a live seeded dashboard → watch a 3-min video →
book a pilot. And you can say the dogfood sentence with a real N.

---

## Phase 10 — Enterprise Hardening (DEFERRED — trigger: a pilot wants to pay)

Deliberately not now. Build the specific item a paying pilot demands, in this order
of likely demand:

- [ ] SSO (SAML/OIDC via WorkOS or authlib) — first enterprise ask
- [ ] Org invitations + member management UI (backend RBAC exists)
- [ ] Billing (Stripe) — only for the hosted tier
- [ ] SOC2 posture doc (you already have: RBAC, audit trails, encryption at rest for
      creds, GDPR erasure — write it down, don't build more)
- [ ] Salesforce bidirectional (after HubSpot proves the pattern)
- [ ] Helm chart / docker-compose production profile for true VPC installs
- [ ] Per-org rate limits + usage metering (LLMCall table already meters cost)

---

## Standing debt register (chip away, never a dedicated "debt sprint")

- [ ] `app/main.py` is ~3,500 lines — extract remaining legacy routes into
      `app/routers/` (leads, analytics, tracking, config). Rule: any endpoint you
      touch for another reason moves out in the same PR
- [ ] Analytics endpoints are not org-scoped (core CRUD is) — scope them before any
      multi-tenant pilot
- [ ] Sync SQLAlchemy inside async FastAPI handlers — fine at pilot scale; revisit
      only if p95 latency complains
- [ ] `Conversation.embedding` pgvector column still lives in a script, not alembic —
      fold into the next migration
- [ ] Frontend bundle is 1.1 MB — route-level code splitting when convenient
- [ ] Husky v10 deprecation warning in pre-commit
- [ ] OAuth mailbox flows are unit-tested against mocks only — do one manual
      round-trip with real Google/Microsoft credentials before demoing that flow
- [ ] `SendingMailbox.last_imap_poll_at` doubles as the OAuth poll timestamp — rename
      to `last_poll_at` in a future migration for honesty

---

## Suggested session breakdown (each ≈ one focused work session)

1. **6.1 + 6.2** — migration 0013, Campaign/Plan/ActionLog models, metrics provider + tests
2. **6.3** — planner + executor + autonomy dial + scheduler job + tests
3. **6.4 + 6.5** — campaigns API + Campaigns page + frontend tests
4. **7.1 + 7.2** — prospecting providers + gated sourcing pipeline + tests
5. **7.3 + 7.4** — triggers (incl. wiring `request_prospecting`) + UI
6. **8.1 + 8.2** — classifier + per-category actions (incl. the OOO-cancels-cadence fix)
7. **8.3 + 8.4** — objection analytics + planner feedback + Inbox/Analytics UI
8. **9.1** — HubSpot bidirectional
9. **9.2** — go live (mostly ops)
10. **9.3** — evidence engine (founder work; no Claude session needed except the video storyboard)

---

*Last updated: 2026-07-16, baseline commit `9dc8de8`. Update this line when the plan changes.*
