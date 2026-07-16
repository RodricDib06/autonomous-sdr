"""
Provenance grounding for generated outreach emails.

Every factual claim in a generated email is matched against the evidence the
pipeline actually collected — research-agent snippets, enrichment fields, the
lead record itself, and the sequence template. Claims with no supporting
source are flagged "unverified" so the approval queue can show reviewers
exactly which sentences the LLM invented.

Design choice: extraction and matching are fully deterministic (sentence
splitting + lexical overlap), not LLM-judged. A grounding check that itself
hallucinates would defeat the point; lexical matching is conservative,
reproducible, and testable. The rules:

  - A sentence is a checkable claim when it contains a factual anchor —
    a number, or business-event vocabulary (funding, growth, hiring, …),
    or an assertion about the prospect's company/industry.
  - A claim is "verified" when some single source contains every numeric
    token of the claim AND at least half of its content words.

The result dict is stored on OutreachEmail.claims and surfaced by the
approval-queue API.
"""

from __future__ import annotations

import json
import logging
import re

log = logging.getLogger(__name__)

MAX_CLAIMS = 8
MIN_CLAIM_TOKENS = 4
OVERLAP_THRESHOLD = 0.5

# Words too common to count as evidence of a factual match
_STOPWORDS = frozenset(
    """a an and are as at be been but by can could did do does for from had has
    have he her his how i if in into is it its just me more most my no not of
    on or our out she so some than that the their them then there these they
    this to up us was we were what when which who will with would you your
    hi hello hey best regards thanks thank cheers dear team really very quick
    question call chat connect minute minutes worth make sense happy let know
    im ive id well get got like also""".split()
)

# Vocabulary that marks a sentence as asserting a checkable business fact
_ANCHOR_RE = re.compile(
    r"""
    \d
    | [$€£]
    | \bpercent\b | %
    | \b(raised?|raising|funding|funded|series|round|investment|investors?)\b
    | \b(grew|grow(?:ing|th)?|expand(?:ed|ing)?|scal(?:ed|ing))\b
    | \b(hir(?:ed|ing)|headcount|team\s+of)\b
    | \b(launch(?:ed|ing)?|announc(?:ed|ing)|acquir(?:ed|ing)|releas(?:ed|ing))\b
    | \b(revenue|valuation|customers?|users?|clients?)\b
    | \b(recently|noticed|came\s+across|saw\s+that|read\s+that|congrats|congratulations)\b
    | \b(industry|space|sector|market)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")


def _tokenize(text: str) -> set[str]:
    """Lowercased content words — stopwords and 1-char fragments dropped."""
    words = re.findall(r"[a-z0-9]+(?:'[a-z]+)?", (text or "").lower())
    return {w for w in words if len(w) > 1 and w not in _STOPWORDS}


def _numbers(text: str) -> set[str]:
    """Numeric tokens, comma/point separators normalised away."""
    return {n.replace(",", "").replace(".", "") for n in _NUMBER_RE.findall(text or "")}


# ---------------------------------------------------------------------------
# Source registry — everything the pipeline actually knows about this lead
# ---------------------------------------------------------------------------

def build_source_registry(lead, enrichment, research: dict | None, template_text: str = "") -> list[dict]:
    """
    Flatten collected evidence into sources: [{id, kind, title, text}, ...].

    Kinds: lead_record | enrichment | web_search | funding_signal | icp_check
    | template. The LLM-written research_summary is deliberately excluded —
    only primary evidence can verify a claim.
    """
    sources: list[dict] = []

    if lead is not None:
        sources.append({
            "id": "lead-record",
            "kind": "lead_record",
            "title": "Lead-provided record",
            "text": f"{lead.name or ''} {lead.email or ''} {lead.company or ''} {lead.source or ''}",
        })

    if enrichment is not None:
        tech = enrichment.tech_stack or []
        tech_str = " ".join(tech) if isinstance(tech, list) else json.dumps(tech)
        sources.append({
            "id": "enrichment",
            "kind": "enrichment",
            "title": f"Enrichment ({enrichment.enrichment_source or 'unknown source'})",
            "text": (
                f"industry {enrichment.industry or ''} "
                f"job title {enrichment.job_title or ''} "
                f"seniority {enrichment.seniority or ''} "
                f"company size {enrichment.company_size or ''} employees "
                f"revenue {enrichment.revenue_estimate or ''} "
                f"tech stack {tech_str}"
            ),
        })

    for i, note in enumerate((research or {}).get("research_notes", [])):
        tool = note.get("tool", "")
        args = note.get("args", {}) or {}
        result = note.get("result", {}) or {}

        if tool == "search_web":
            for j, hit in enumerate(result.get("results", []) or []):
                sources.append({
                    "id": f"research-{i}-{j}",
                    "kind": "web_search",
                    "title": hit.get("title") or f"Web search: {args.get('query', '')}",
                    "text": f"{hit.get('title', '')} {hit.get('snippet', '')}",
                })
        elif tool == "check_funding":
            sources.append({
                "id": f"research-{i}",
                "kind": "funding_signal",
                "title": f"Funding signals: {args.get('company', '')}",
                "text": (
                    f"recent funding {'yes' if result.get('recent_funding') else 'no'} "
                    f"headcount growth {result.get('headcount_growth', 0)} percent in 6 months"
                ),
            })
        elif tool == "verify_icp":
            sources.append({
                "id": f"research-{i}",
                "kind": "icp_check",
                "title": f"ICP check: {args.get('company', '')}",
                "text": (
                    f"industry match {'yes' if result.get('industry_match') else 'no'} "
                    f"size match {'yes' if result.get('size_match') else 'no'} "
                    f"industry {args.get('industry', '')} size {args.get('size', '')}"
                ),
            })

    if template_text:
        sources.append({
            "id": "template",
            "kind": "template",
            "title": "Sequence template (our own copy)",
            "text": template_text,
        })

    return sources


# ---------------------------------------------------------------------------
# Claim extraction
# ---------------------------------------------------------------------------

def extract_claims(subject: str, body: str) -> list[str]:
    """
    Sentences that assert something checkable about the world. Greetings,
    sign-offs, and pure calls-to-action carry no factual anchor and are
    skipped; the cap keeps the approval UI readable.
    """
    claims: list[str] = []
    seen: set[str] = set()

    candidates = [subject or ""] + _SENTENCE_SPLIT_RE.split(body or "")
    for sentence in candidates:
        sentence = sentence.strip()
        if not sentence or len(_tokenize(sentence)) < MIN_CLAIM_TOKENS:
            continue
        if not _ANCHOR_RE.search(sentence):
            continue
        key = " ".join(sorted(_tokenize(sentence)))
        if key in seen:
            continue
        seen.add(key)
        claims.append(sentence)
        if len(claims) >= MAX_CLAIMS:
            break

    return claims


# ---------------------------------------------------------------------------
# Claim ↔ source matching
# ---------------------------------------------------------------------------

def match_claim(claim: str, sources: list[dict]) -> dict:
    """
    Best-supporting source for a claim, scored by content-word overlap.
    Numbers are the hard gate: a single source must contain every numeric
    token in the claim, or it cannot verify it (invented metrics are the
    #1 hallucination risk in sales email).
    """
    claim_tokens = _tokenize(claim)
    claim_numbers = _numbers(claim)

    best: dict = {"status": "unverified", "score": 0.0, "source_id": None,
                  "source_kind": None, "source_title": None, "source_excerpt": None}
    if not claim_tokens:
        return best

    for source in sources:
        text = source.get("text", "")
        source_tokens = _tokenize(text)
        if claim_numbers and not claim_numbers <= _numbers(text):
            continue
        score = len(claim_tokens & source_tokens) / len(claim_tokens)
        if score > best["score"]:
            best.update({
                "score": round(score, 3),
                "source_id": source["id"],
                "source_kind": source["kind"],
                "source_title": source["title"],
                "source_excerpt": text.strip()[:240],
            })

    if best["score"] >= OVERLAP_THRESHOLD:
        best["status"] = "verified"
    return best


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def ground_email(
    subject: str,
    body: str,
    lead=None,
    enrichment=None,
    research: dict | None = None,
    template_text: str = "",
) -> dict:
    """
    Full grounding report for one generated email. Never raises — grounding
    is advisory and must not block outreach generation.
    """
    try:
        sources = build_source_registry(lead, enrichment, research, template_text)
        claims = extract_claims(subject, body)

        results = []
        for claim in claims:
            match = match_claim(claim, sources)
            results.append({"text": claim, **match})

        verified = sum(1 for r in results if r["status"] == "verified")
        unverified = len(results) - verified
        return {
            "claims": results,
            "verified": verified,
            "unverified": unverified,
            "grounding_score": round(verified / len(results), 3) if results else 1.0,
            "sources": [{"id": s["id"], "kind": s["kind"], "title": s["title"]} for s in sources],
        }
    except Exception as e:
        log.warning(f"[provenance] grounding failed: {e}")
        return {"claims": [], "verified": 0, "unverified": 0, "grounding_score": None,
                "sources": [], "error": str(e)}
