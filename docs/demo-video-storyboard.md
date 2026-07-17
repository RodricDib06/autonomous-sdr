# Demo video storyboard — 3 minutes, one continuous take

> ROADMAP 9.3. The order below is deliberate: it tells the **trust story**
> (the #1 buyer objection to AI SDRs) before the capability story. Record at
> 1440p over the seeded demo org; script lines are suggestions, speak them
> in your own voice. Target: 3:00 ± 15s. Tool: Screen Studio / Loom.

## Cold open — the claim (0:00–0:15)

Dashboard, already populated.

> "This is AutonomousSDR — a self-hosted AI SDR that runs inside your own
> VPC. I'm going to show you the part every AI SDR demo skips: how you
> stop it from embarrassing you."

## Scene 1 — a lead arrives and gets argued about (0:15–0:45)

Trigger a webhook lead (or `POST /ingest/form` from a terminal split).
Open the lead → Intel tab while the pipeline streams.

> "A lead just landed. Ten agents qualify it — including an adversarial
> debate: one agent argues for the lead, one against, a third arbitrates.
> You can read the whole argument."

Show the debate transcript for ~5 seconds. Don't explain BANT.

## Scene 2 — the Fact Check panel (0:45–1:20) ⭐ the money moment

Approvals page, a draft with one unverified claim.

> "Before anything sends, every factual claim in the email is traced to a
> source — the research snippet that backs it. This claim came from a real
> funding announcement. This one, the model made up — so it's flagged, and
> I can fix it before a prospect ever sees it."

Click the verified claim → source excerpt unfolds. Point at the unverified
one. Edit the line inline, approve. **This scene converts the hallucination
objection into your differentiator — give it the most screen time.**

## Scene 3 — the autonomy dial (1:20–1:40)

Still on Approvals; flip draft → approve → auto.

> "Teams start in draft-only, graduate to approve-each-email, and switch to
> full auto when the output has earned it. The same dial exists one level
> up — for strategy."

## Scene 4 — the campaign agent (1:40–2:15)

Campaigns page, a behind-pace campaign with a pending plan.

> "This campaign is behind quota — and the agent knows. It diagnosed why,
> wants to pause the weak sequence, drafts a new variant answering the
> objection prospects actually raised in replies, and asks to source thirty
> more leads. I approve the plan; it executes and reports back weekly."

Approve the plan; show the per-action checkmarks land, then 3 seconds of
the agent report.

## Scene 5 — backtest on their data (2:15–2:45)

Backtests page, the seeded run.

> "And you don't have to take the scoring on faith — upload last quarter's
> CRM export and it re-qualifies every lead against what actually closed.
> Here it flagged 80% of the closed-won deals as Hot, with 2.7x lift over
> base rate. Argue with your own data, not mine."

Hover a calibration bar; click "Misses only" briefly.

## Close — ROI + the wedge (2:45–3:00)

Analytics ROI panel.

> "Every model call is metered, so cost-per-meeting versus a human SDR is
> computed from your own pipeline — not a slide. Self-hosted, your data
> never leaves your infrastructure. Link below to try the live demo."

---

## Pre-flight checklist

- [ ] Seeded demo org loaded (`scripts/seed_demo_data.py`) with: 1 pending
      approval containing an unverified claim, 1 behind-pace campaign with a
      pending plan, 1 completed backtest, populated ROI panel
- [ ] `DEMO_READONLY_EMAILS` demo account works for the "try it" link
- [ ] Browser zoom 110%, sidebar visible, no devtools, notifications off
- [ ] Do a full silent click-through once before recording; kill any scene
      that needs a second sentence of explanation

## Cut list (if over 3:10)

Cut in this order: Scene 3 (fold one line into Scene 2's approve click),
the Misses-only click in Scene 5, the debate transcript lingering shot.
Never cut Scene 2.
