import { useState, useRef, type JSX } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Search, Filter, Download, X, ChevronRight,
  Building2, Tag, Archive, Trash2, RefreshCw,
  Mail, Calendar, MessageSquare, GitBranch, Zap,
  CheckCircle2, XCircle, Clock, Sparkles, TrendingUp, TrendingDown, Minus,
  Brain, Timer, ExternalLink, Globe, Users2, Keyboard, Copy,
} from "lucide-react";
import { toast } from "sonner";
import {
  leadsApi, intentApi, outreachApi, bookingApi, conversationsApi,
  pipelineApi, analyticsApi, optimizationApi, decayApi, enrichmentApi, crmApi,
  debateApi, briefApi, signalApi, referralChainApi,
} from "../lib/api";
import { useKeyboardShortcuts, SHORTCUTS } from "../hooks/useKeyboardShortcuts";
import type { LeadDetail, CRMPushResult, DebateVoice, TriggerSignal, ReferralLeadStub } from "../types";
import { Header } from "../components/layout/Header";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Badge } from "../components/ui/badge";
import { Card } from "../components/ui/card";
import { VerdictBadge } from "../components/VerdictBadge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Progress } from "../components/ui/progress";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { formatDate, scoreColor, cn } from "../lib/utils";

const STATUS_COLORS: Record<string, string> = {
  complete: "success",
  processing: "warning",
  pending: "secondary",
  failed: "destructive",
};

// ── Tab definitions ────────────────────────────────────────────────────────

const TABS = [
  { id: "profile",  label: "Profile",  icon: Building2 },
  { id: "intel",    label: "Intel",    icon: Brain },
  { id: "intent",   label: "Intent",   icon: Zap },
  { id: "outreach", label: "Outreach", icon: Mail },
  { id: "activity", label: "Activity", icon: MessageSquare },
  { id: "trace",    label: "Trace",    icon: GitBranch },
] as const;

type TabId = typeof TABS[number]["id"];

// ── Tab content components ─────────────────────────────────────────────────

const BANT_LABELS: Record<string, string> = {
  budget: "Budget", authority: "Authority", need: "Need", timeline: "Timeline",
};
const BANT_DESCRIPTIONS: Record<string, string> = {
  budget: "Confirmed spending power", authority: "Decision-making power",
  need: "Clear problem fit", timeline: "Urgency to act",
};

function scoreColorClass(s: number) {
  return s >= 0.7 ? "text-emerald-400" : s >= 0.4 ? "text-orange-400" : "text-red-400";
}
function barColorClass(s: number) {
  return s >= 0.7 ? "bg-emerald-500" : s >= 0.4 ? "bg-orange-400" : "bg-red-500";
}

// ── ReferralStubCard — shared by ProfileTab referral chain ─────────────────

function ReferralStubCard({ stub }: { stub: ReferralLeadStub }) {
  return (
    <div className="flex items-center gap-2.5 text-xs">
      <div className="w-7 h-7 rounded-full bg-gradient-to-br from-blue-600/60 to-indigo-600/60 flex items-center justify-center text-[9px] font-bold text-white shrink-0">
        {stub.name.slice(0, 2).toUpperCase()}
      </div>
      <div className="flex-1 min-w-0">
        <p className="font-medium truncate">{stub.name}</p>
        <p className="text-[10px] text-muted-foreground truncate">
          {stub.job_title ?? stub.company}{stub.seniority ? ` · ${stub.seniority}` : ""}
        </p>
      </div>
      <VerdictBadge verdict={stub.final_verdict} />
    </div>
  );
}

// ── ProfileTab ─────────────────────────────────────────────────────────────

function ProfileTab({ lead }: { lead: LeadDetail }) {
  const bant = lead.verdict?.bant_scores;

  // CRM push state
  const [crmResult, setCrmResult] = useState<CRMPushResult | null>(null);
  const [crmOpen, setCrmOpen] = useState(false);
  const [crmFormat, setCrmFormat] = useState<"hubspot" | "salesforce" | "pipedrive">("hubspot");

  const { data: weights } = useQuery({
    queryKey: ["optimization-weights"],
    queryFn: optimizationApi.currentWeights,
    staleTime: 60_000,
  });

  const { data: closeProbData, isLoading: cpLoading } = useQuery({
    queryKey: ["close-probability", lead.id],
    queryFn: () => leadsApi.closeProbability(lead.id),
    enabled: !!lead.verdict?.bant_scores,
    staleTime: 120_000,
    retry: false,
  });

  const { data: similarData } = useQuery({
    queryKey: ["similar", lead.id],
    queryFn: () => enrichmentApi.similar(lead.id, 5),
    staleTime: 120_000,
    enabled: !!lead.verdict?.final_verdict,
  });

  const [showExplanation, setShowExplanation] = useState(false);
  const { data: explanation, isFetching: explanationLoading } = useQuery({
    queryKey: ["verdict-explanation", lead.id],
    queryFn: () => analyticsApi.verdictExplanation(lead.id),
    enabled: showExplanation && !!lead.verdict?.final_verdict,
    staleTime: 300_000,
    retry: false,
  });

  const { mutate: pushCRM, isPending: pushing } = useMutation({
    mutationFn: () => crmApi.push(lead.id, crmFormat),
    onSuccess: (data) => { setCrmResult(data); toast.success(`Formatted for ${crmFormat}`); },
    onError: () => toast.error("CRM push failed"),
  });

  const { mutate: webEnrich, isPending: enriching, data: enrichData } = useMutation({
    mutationFn: () => enrichmentApi.webEnrich(lead.id),
    onSuccess: (d) => {
      if (d.error) toast.error(`Enrichment: ${d.error}`);
      else toast.success(`Found ${d.signals.length} signals · ${d.tech_stack.length} tech`);
    },
    onError: () => toast.error("Web enrichment failed"),
  });

  const { data: chainData } = useQuery({
    queryKey: ["referral-chain", lead.id],
    queryFn: () => referralChainApi.get(lead.id),
    staleTime: 300_000,
  });

  const bantEntries = bant ? Object.entries(bant) : [];
  const weightedScore = bantEntries.length > 0 && weights
    ? bantEntries.reduce((sum, [key, val]) => {
        const w = (weights as Record<string, number>)[key] ?? (1 / bantEntries.length);
        return sum + (typeof val === "number" ? val : 0) * w;
      }, 0)
    : null;

  return (
    <div className="space-y-5">
      {/* Verdict + confidence */}
      <div className="flex items-center gap-3">
        <VerdictBadge verdict={lead.verdict?.final_verdict} />
        {lead.verdict?.confidence_score != null && (
          <div className="flex items-center gap-2 flex-1">
            <Progress
              value={(lead.verdict.confidence_score ?? 0) * 100}
              className="h-2 flex-1"
              indicatorClassName={
                lead.verdict.confidence_score >= 0.7 ? "bg-emerald-500" :
                lead.verdict.confidence_score >= 0.4 ? "bg-orange-500" : "bg-red-500"
              }
            />
            <span className="text-sm font-medium w-10 text-right">
              {Math.round(lead.verdict.confidence_score * 100)}%
            </span>
          </div>
        )}
      </div>

      {/* BANT Visual Breakdown */}
      {bantEntries.length > 0 && (
        <section className="rounded-xl border border-border bg-card/60 overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-border/60">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">BANT Qualification</h3>
            {weightedScore != null && (
              <span className={cn("text-xs font-bold", scoreColorClass(weightedScore))}>
                {Math.round(weightedScore * 100)}% weighted
              </span>
            )}
          </div>
          <div className="px-4 py-3 space-y-4">
            {bantEntries.map(([key, rawScore]) => {
              const score = typeof rawScore === "number" ? rawScore : 0;
              const weight = weights ? ((weights as Record<string, number>)[key] ?? 0.25) : 0.25;
              const contribution = score * weight;
              return (
                <div key={key}>
                  <div className="flex items-center justify-between mb-1.5">
                    <div>
                      <span className="text-xs font-semibold">{BANT_LABELS[key] ?? key}</span>
                      <span className="text-[10px] text-muted-foreground ml-2">{BANT_DESCRIPTIONS[key]}</span>
                    </div>
                    <div className="flex items-center gap-2 text-xs">
                      <span className="text-muted-foreground">{Math.round(weight * 100)}% wt</span>
                      <span className={cn("font-bold tabular-nums w-9 text-right", scoreColorClass(score))}>
                        {Math.round(score * 100)}%
                      </span>
                    </div>
                  </div>
                  <div className="relative h-2 rounded-full bg-secondary overflow-hidden">
                    <div
                      className={cn("absolute inset-y-0 left-0 rounded-full transition-all", barColorClass(score))}
                      style={{ width: `${score * 100}%` }}
                    />
                  </div>
                  <p className="text-[10px] text-muted-foreground mt-0.5 text-right">
                    contributes {Math.round(contribution * 100)}% to score
                  </p>
                </div>
              );
            })}
          </div>
          {lead.verdict?.icp_match != null && (
            <div className="flex items-center gap-2 px-4 py-2.5 border-t border-border/60 text-xs">
              {lead.verdict.icp_match
                ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                : <XCircle className="w-3.5 h-3.5 text-red-400 shrink-0" />}
              <span className="text-muted-foreground">
                {lead.verdict.icp_match ? "Matches Ideal Customer Profile" : "Outside Ideal Customer Profile"}
              </span>
            </div>
          )}
        </section>
      )}

      {/* Lookalike Score */}
      <section className="rounded-xl border border-border bg-card/60 overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border/60">
          <Users2 className="w-3.5 h-3.5 text-muted-foreground" />
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Lookalike Score</h3>
          <span className="ml-auto text-[10px] text-muted-foreground/60">vs. converted leads</span>
        </div>
        {lead.lookalike_score == null ? (
          <p className="px-4 py-4 text-xs text-muted-foreground">
            Not computed yet — runs nightly after at least 5 conversions.
          </p>
        ) : (
          <div className="px-4 py-4 space-y-3">
            <div className="flex items-end gap-4">
              <div>
                <p className={cn("text-4xl font-bold tabular-nums", scoreColorClass(lead.lookalike_score))}>
                  {Math.round(lead.lookalike_score * 100)}%
                </p>
                <p className="text-[10px] text-muted-foreground mt-0.5">similarity to your best-fit customers</p>
              </div>
              <div className="flex items-center gap-1.5 text-xs mb-1 text-muted-foreground">
                {lead.lookalike_score >= 0.7
                  ? <><TrendingUp className="w-3.5 h-3.5 text-emerald-400" /><span className="text-emerald-400">Strong fit</span></>
                  : lead.lookalike_score >= 0.4
                  ? <><Minus className="w-3.5 h-3.5 text-orange-400" /><span className="text-orange-400">Moderate fit</span></>
                  : <><TrendingDown className="w-3.5 h-3.5 text-red-400" /><span className="text-red-400">Weak fit</span></>}
              </div>
            </div>
            <div className="relative h-2.5 rounded-full bg-secondary overflow-hidden">
              <div
                className={cn("absolute inset-y-0 left-0 rounded-full transition-all", barColorClass(lead.lookalike_score))}
                style={{ width: `${lead.lookalike_score * 100}%` }}
              />
            </div>
            <p className="text-[10px] text-muted-foreground/70 leading-relaxed">
              Computed via 8-dimensional cosine similarity across BANT scores, seniority, company size, industry, and engagement. Updated nightly.
            </p>
          </div>
        )}
      </section>

      {/* ML Close Probability */}
      <section className="rounded-xl border border-violet-500/20 bg-violet-500/5 overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-violet-500/20">
          <Brain className="w-3.5 h-3.5 text-violet-400" />
          <h3 className="text-xs font-semibold uppercase tracking-wide text-violet-300">ML Close Probability</h3>
        </div>
        {cpLoading ? (
          <div className="px-4 py-5 space-y-2">
            <div className="skeleton h-8 w-24 rounded" />
            <div className="skeleton h-2 rounded" />
          </div>
        ) : !closeProbData ? (
          <p className="px-4 py-4 text-xs text-muted-foreground">Not available — lead has no BANT scores.</p>
        ) : closeProbData.fallback ? (
          <div className="px-4 py-4 space-y-1">
            <p className="text-xs text-muted-foreground">{closeProbData.fallback_reason ?? "Insufficient training data."}</p>
            <p className="text-[10px] text-muted-foreground/60">Mark leads as converted or lost to train the model.</p>
          </div>
        ) : (
          <div className="px-4 py-4 space-y-4">
            <div className="flex items-end gap-4">
              <div>
                <p className={cn("text-4xl font-bold tabular-nums",
                  closeProbData.probability >= 0.7 ? "text-emerald-400" :
                  closeProbData.probability >= 0.4 ? "text-orange-400" : "text-red-400"
                )}>
                  {Math.round(closeProbData.probability * 100)}%
                </p>
                <p className="text-[10px] text-muted-foreground mt-0.5">predicted close probability</p>
              </div>
              {closeProbData.bant_score != null && Math.abs(closeProbData.divergence) >= 0.03 && (
                <div className="flex items-center gap-1.5 text-xs mb-1">
                  {closeProbData.divergence > 0
                    ? <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
                    : closeProbData.divergence < 0
                    ? <TrendingDown className="w-3.5 h-3.5 text-orange-400" />
                    : <Minus className="w-3.5 h-3.5 text-muted-foreground" />}
                  <span className={closeProbData.divergence > 0 ? "text-emerald-400" : "text-orange-400"}>
                    {closeProbData.divergence > 0 ? "+" : ""}{Math.round(closeProbData.divergence * 100)}% vs BANT
                  </span>
                </div>
              )}
            </div>
            <div className="relative h-2 rounded-full bg-secondary overflow-hidden">
              <div
                className={cn("absolute inset-y-0 left-0 rounded-full transition-all", barColorClass(closeProbData.probability))}
                style={{ width: `${closeProbData.probability * 100}%` }}
              />
            </div>
            {closeProbData.divergence_note && (
              <p className="text-[11px] text-muted-foreground italic leading-relaxed">{closeProbData.divergence_note}</p>
            )}
            {closeProbData.feature_importances && (
              <div className="space-y-2">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Model feature weights</p>
                {Object.entries(closeProbData.feature_importances)
                  .sort(([, a], [, b]) => Math.abs(b) - Math.abs(a))
                  .slice(0, 6)
                  .map(([name, importance]) => {
                    const pos = importance >= 0;
                    const pct = Math.round(Math.abs(importance) * 100);
                    return (
                      <div key={name} className="flex items-center gap-2 text-[11px]">
                        <span className="text-muted-foreground w-24 shrink-0 truncate">
                          {name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                        </span>
                        <div className="flex-1 flex items-center gap-1">
                          <div className="flex-1 h-1.5 rounded-full bg-secondary overflow-hidden">
                            <div className={cn("h-full rounded-full", pos ? "bg-emerald-500" : "bg-red-500")} style={{ width: `${pct}%` }} />
                          </div>
                          <span className={cn("w-8 text-right", pos ? "text-emerald-400" : "text-red-400")}>
                            {pos ? "+" : "−"}{pct}%
                          </span>
                        </div>
                      </div>
                    );
                  })}
              </div>
            )}
            {closeProbData.model_info && (
              <p className="text-[10px] text-muted-foreground/60 pt-1 border-t border-border/40">
                Model trained on {closeProbData.model_info.trained_on} leads
                ({closeProbData.model_info.converted} converted · {closeProbData.model_info.lost} lost)
              </p>
            )}
          </div>
        )}
      </section>

      {/* Similar Leads */}
      {(similarData?.similar ?? []).length > 0 && (
        <section className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-1.5">
            <Users2 className="w-3.5 h-3.5" /> Similar Leads
          </h3>
          <div className="space-y-1.5">
            {similarData!.similar.map((s) => (
              <div key={s.id} className="flex items-center gap-3 rounded-lg px-3 py-2 bg-secondary/30 text-xs">
                <div className="w-6 h-6 rounded-full bg-gradient-to-br from-violet-600/60 to-indigo-600/60 flex items-center justify-center text-[9px] font-bold text-white shrink-0">
                  {s.name.slice(0, 2).toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-medium truncate">{s.name}</p>
                  <p className="text-[10px] text-muted-foreground truncate">{s.job_title ?? s.company}</p>
                </div>
                <VerdictBadge verdict={s.verdict as "Hot" | "Warm" | "Cold" | null} />
                <span className="text-violet-400 font-semibold w-10 text-right">{Math.round(s.similarity * 100)}%</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Referral Chain */}
      {chainData?.has_chain && (
        <section className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-1.5">
            <GitBranch className="w-3.5 h-3.5" /> Org-Chart Referral Chain
          </h3>

          {chainData.referred_by && (
            <div className="rounded-lg border border-blue-500/20 bg-blue-500/5 p-3 space-y-1">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-blue-400 mb-2">Discovered via</p>
              <ReferralStubCard stub={chainData.referred_by} />
            </div>
          )}

          {chainData.discovered.length > 0 && (
            <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3 space-y-2">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-emerald-400 mb-2">
                {chainData.discovered.length} lead{chainData.discovered.length !== 1 ? "s" : ""} discovered by this lead
              </p>
              <div className="space-y-1.5">
                {chainData.discovered.map((stub) => (
                  <ReferralStubCard key={stub.id} stub={stub} />
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      {/* Web Signal Enrichment */}
      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-1.5">
            <Globe className="w-3.5 h-3.5" /> Web Signals
          </h3>
          <Button variant="outline" size="sm" onClick={() => webEnrich()} loading={enriching} className="h-6 text-[10px] px-2">
            Scrape
          </Button>
        </div>
        {enrichData && (
          <div className="rounded-lg border border-border p-3 space-y-2">
            {enrichData.error && (
              <p className="text-[10px] text-red-400">{enrichData.error}</p>
            )}
            {enrichData.signals.length > 0 && (
              <div className="space-y-1">
                {enrichData.signals.map((sig, i) => (
                  <div key={i} className="flex items-start gap-2 text-[10px]">
                    <CheckCircle2 className="w-3 h-3 text-emerald-400 shrink-0 mt-0.5" />
                    <span className="text-muted-foreground">{sig.text}</span>
                  </div>
                ))}
              </div>
            )}
            {enrichData.tech_stack.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {enrichData.tech_stack.map((t) => (
                  <Badge key={t} variant="secondary" className="text-[10px] px-1.5 py-0">{t}</Badge>
                ))}
              </div>
            )}
            {enrichData.signals.length === 0 && enrichData.tech_stack.length === 0 && !enrichData.error && (
              <p className="text-[10px] text-muted-foreground">No public signals detected on {enrichData.domain ?? "this domain"}.</p>
            )}
            <p className="text-[9px] text-muted-foreground/50">{enrichData.pages_fetched} page{enrichData.pages_fetched !== 1 ? "s" : ""} fetched</p>
          </div>
        )}
      </section>

      {/* CRM Push */}
      <section className="space-y-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-1.5">
          <ExternalLink className="w-3.5 h-3.5" /> Push to CRM
        </h3>
        <div className="flex gap-2">
          {(["hubspot", "salesforce", "pipedrive"] as const).map((fmt) => (
            <button
              key={fmt}
              onClick={() => setCrmFormat(fmt)}
              className={cn(
                "flex-1 py-1.5 rounded-lg border text-[10px] font-medium capitalize transition-all",
                crmFormat === fmt
                  ? "border-violet-500/50 bg-violet-500/10 text-violet-300"
                  : "border-border text-muted-foreground hover:border-border/80"
              )}
            >
              {fmt}
            </button>
          ))}
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => { setCrmOpen(true); pushCRM(); }}
          loading={pushing}
          className="w-full gap-1.5 text-xs"
        >
          <ExternalLink className="w-3.5 h-3.5" />
          Push to {crmFormat.charAt(0).toUpperCase() + crmFormat.slice(1)}
        </Button>
        {crmResult && crmOpen && (
          <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3 space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-[10px] font-medium text-emerald-400">✓ Ready for {crmResult.format}</p>
              <button
                onClick={() => { navigator.clipboard.writeText(JSON.stringify(crmResult.payload, null, 2)); toast.success("Payload copied"); }}
                className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground"
              >
                <Copy className="w-3 h-3" /> Copy
              </button>
            </div>
            <pre className="text-[9px] text-muted-foreground overflow-x-auto max-h-32 rounded bg-secondary/30 p-2">
              {JSON.stringify(crmResult.payload, null, 2)}
            </pre>
          </div>
        )}
      </section>

      {/* Verdict Explanation */}
      {lead.verdict?.final_verdict && (
        <section className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">AI Reasoning</h3>
            {!showExplanation && (
              <button
                onClick={() => setShowExplanation(true)}
                className="text-[10px] text-violet-400 hover:text-violet-300 underline underline-offset-2"
              >
                Explain verdict
              </button>
            )}
          </div>
          {/* Always show raw reasoning as fallback */}
          {lead.verdict?.reasoning && !showExplanation && (
            <p className="text-sm text-muted-foreground leading-relaxed bg-secondary/50 rounded-lg p-3">
              {lead.verdict.reasoning}
            </p>
          )}
          {showExplanation && (
            <div className="bg-secondary/50 rounded-lg p-3 space-y-3">
              {explanationLoading ? (
                <p className="text-xs text-muted-foreground animate-pulse">Generating explanation…</p>
              ) : explanation ? (
                <>
                  <p className="text-sm text-foreground leading-relaxed">{explanation.summary}</p>
                  {explanation.key_drivers.length > 0 && (
                    <div className="space-y-1">
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Key Drivers</p>
                      {explanation.key_drivers.map((d, i) => (
                        <p key={i} className="text-xs text-muted-foreground flex gap-1.5">
                          <span className="text-violet-400 shrink-0">›</span>{d}
                        </p>
                      ))}
                    </div>
                  )}
                  {explanation.counterfactual && (
                    <div className="border-t border-border pt-2">
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground mb-1">What Would Change It</p>
                      <p className="text-xs text-muted-foreground italic">{explanation.counterfactual}</p>
                    </div>
                  )}
                </>
              ) : (
                <p className="text-sm text-muted-foreground leading-relaxed">
                  {lead.verdict?.reasoning ?? "No reasoning available."}
                </p>
              )}
            </div>
          )}
        </section>
      )}

      {/* Contact + Enrichment */}
      <section className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Contact</h3>
        <div className="grid grid-cols-2 gap-3 text-sm">
          {[
            ["Company", lead.company],
            ["Source", lead.source?.replace(/_/g, " ")],
            ["Status", null],
            ["Created", formatDate(lead.created_at)],
          ].map(([label, value]) => (
            <div key={label as string}>
              <p className="text-muted-foreground text-xs mb-0.5">{label}</p>
              {label === "Status" ? (
                <Badge variant={STATUS_COLORS[lead.status] as Parameters<typeof Badge>[0]["variant"]}>{lead.status}</Badge>
              ) : (
                <p className="font-medium capitalize">{value ?? "—"}</p>
              )}
            </div>
          ))}
        </div>
      </section>

      {lead.enrichment && (
        <section className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Enrichment</h3>
          <div className="grid grid-cols-2 gap-3 text-sm">
            {[
              ["Job Title", lead.enrichment.job_title],
              ["Seniority", lead.enrichment.seniority],
              ["Company Size", lead.enrichment.company_size],
              ["Industry", lead.enrichment.industry],
              ["Revenue", lead.enrichment.revenue_estimate],
            ].map(([label, value]) =>
              value ? (
                <div key={label as string}>
                  <p className="text-muted-foreground text-xs mb-0.5">{label}</p>
                  <p className="font-medium">{value}</p>
                </div>
              ) : null
            )}
          </div>
          {lead.enrichment.tech_stack && lead.enrichment.tech_stack.length > 0 && (
            <div>
              <p className="text-muted-foreground text-xs mb-1.5">Tech Stack</p>
              <div className="flex flex-wrap gap-1.5">
                {lead.enrichment.tech_stack.map((t) => (
                  <Badge key={t} variant="secondary" className="text-xs">{t}</Badge>
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      {/* Data Quality */}
      <section className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Data Quality</h3>
        <div className="grid grid-cols-2 gap-3">
          {[
            ["Quality Score", lead.data_quality_score],
            ["Completeness", lead.completeness_score],
          ].map(([label, v]) => (
            <div key={label as string} className="rounded-lg bg-secondary/50 p-3 text-center">
              <p className={cn("text-2xl font-bold", scoreColor(v as number | null))}>
                {v != null ? Math.round((v as number) * 100) : "—"}
              </p>
              <p className="text-xs text-muted-foreground mt-0.5">{label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Tags */}
      {lead.tags && lead.tags.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Tags</h3>
          <div className="flex flex-wrap gap-1.5">
            {lead.tags.map((t) => (
              <Badge key={t} variant="default" className="text-xs gap-1">
                <Tag className="w-2.5 h-2.5" />{t}
              </Badge>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

// ── IntelTab ───────────────────────────────────────────────────────────────

const SIGNAL_LABELS: Record<string, { label: string; color: string }> = {
  funding_trigger:     { label: "Funding",     color: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20" },
  job_posting_trigger: { label: "Hiring",      color: "text-blue-400 bg-blue-500/10 border-blue-500/20" },
  news_trigger:        { label: "News",         color: "text-violet-400 bg-violet-500/10 border-violet-500/20" },
  job_change_trigger:  { label: "Job Change",   color: "text-orange-400 bg-orange-500/10 border-orange-500/20" },
};

function DebateVoiceCard({ voice, role }: { voice: DebateVoice; role: "advocate" | "critic" }) {
  const isAdvocate = role === "advocate";
  return (
    <div className={cn("rounded-lg border p-3 space-y-2 text-xs", isAdvocate ? "border-emerald-500/30 bg-emerald-500/5" : "border-red-500/30 bg-red-500/5")}>
      <div className="flex items-center justify-between">
        <span className={cn("font-semibold text-[11px] uppercase tracking-wide", isAdvocate ? "text-emerald-400" : "text-red-400")}>
          {isAdvocate ? "Advocate" : "Critic"}
        </span>
        <Badge variant="secondary" className="text-[10px] capitalize">{voice.verdict}</Badge>
      </div>
      <div className="grid grid-cols-2 gap-1.5">
        {Object.entries(voice.bant_scores).map(([dim, score]) => (
          <div key={dim} className="flex items-center justify-between gap-1">
            <span className="capitalize text-muted-foreground">{dim}</span>
            <span className={cn("font-mono font-medium", scoreColorClass(score))}>{Math.round(score * 100)}%</span>
          </div>
        ))}
      </div>
      <p className="text-muted-foreground leading-relaxed">{voice.reasoning}</p>
    </div>
  );
}

function IntelTab({ leadId }: { leadId: string }) {
  const { data: debate, isLoading: debateLoading } = useQuery({
    queryKey: ["debate", leadId],
    queryFn: () => debateApi.get(leadId),
    enabled: !!leadId,
  });

  const { data: brief, isLoading: briefLoading } = useQuery({
    queryKey: ["brief", leadId],
    queryFn: () => briefApi.get(leadId),
    enabled: !!leadId,
  });

  const { data: signalData, isLoading: signalsLoading } = useQuery({
    queryKey: ["trigger-signals", leadId],
    queryFn: () => signalApi.forLead(leadId),
    enabled: !!leadId,
  });

  const transcript = debate?.debate_transcript ?? null;
  const briefData = brief?.brief ?? null;
  const signals: TriggerSignal[] = signalData?.signals ?? [];

  return (
    <div className="space-y-6">

      {/* ── Adversarial BANT Debate ── */}
      <section className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-1.5">
          <Brain className="w-3.5 h-3.5" /> Adversarial BANT Debate
        </h3>
        {debateLoading ? (
          <div className="space-y-2">{[...Array(2)].map((_, i) => <div key={i} className="skeleton h-24 rounded" />)}</div>
        ) : !transcript ? (
          <p className="text-xs text-muted-foreground">No debate data yet. Pipeline must complete first.</p>
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <DebateVoiceCard voice={transcript.advocate} role="advocate" />
              <DebateVoiceCard voice={transcript.critic} role="critic" />
            </div>
            {transcript.contested_dimensions.length > 0 && (
              <div className="flex flex-wrap gap-1.5 items-center">
                <span className="text-[10px] text-muted-foreground uppercase tracking-wide">Contested:</span>
                {transcript.contested_dimensions.map((d) => (
                  <span key={d} className="text-[10px] px-1.5 py-0.5 rounded bg-orange-500/10 border border-orange-500/20 text-orange-400 capitalize">{d}</span>
                ))}
              </div>
            )}
            <div className="rounded-lg bg-secondary/40 border border-border p-3 space-y-1">
              <div className="flex items-center justify-between text-xs">
                <span className="font-semibold text-muted-foreground">Synthesis</span>
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-muted-foreground">Confidence</span>
                  <span className={cn("font-mono font-bold text-sm", scoreColorClass(transcript.confidence_score))}>
                    {Math.round(transcript.confidence_score * 100)}%
                  </span>
                </div>
              </div>
              <p className="text-xs text-muted-foreground leading-relaxed">{transcript.synthesis_reasoning}</p>
            </div>
          </div>
        )}
      </section>

      {/* ── Pre-call Brief ── */}
      <section className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-1.5">
          <Calendar className="w-3.5 h-3.5" /> Pre-Call Brief
        </h3>
        {briefLoading ? (
          <div className="skeleton h-32 rounded" />
        ) : !briefData ? (
          <p className="text-xs text-muted-foreground">
            {brief?.booking_id ? "Brief is being generated…" : "No confirmed booking yet. Brief generates on booking confirmation."}
          </p>
        ) : (
          <div className="space-y-3">
            {brief?.start_time && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Clock className="w-3.5 h-3.5 shrink-0" />
                Meeting: {new Date(brief.start_time).toLocaleString()}
              </div>
            )}
            <div className="rounded-lg border border-border bg-secondary/30 p-3 space-y-1">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Company Snapshot</p>
              <p className="text-xs leading-relaxed">{briefData.company_snapshot}</p>
            </div>
            <div className="rounded-lg border border-border bg-secondary/30 p-3 space-y-1">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Lead Context</p>
              <p className="text-xs leading-relaxed">{briefData.lead_context}</p>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-3 space-y-1.5">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-red-400">Likely Objections</p>
                <ul className="space-y-1">
                  {briefData.likely_objections.map((o, i) => (
                    <li key={i} className="text-xs text-muted-foreground flex gap-1.5"><span className="text-red-400 shrink-0">·</span>{o}</li>
                  ))}
                </ul>
              </div>
              <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3 space-y-1.5">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-emerald-400">Recommended Angles</p>
                <ul className="space-y-1">
                  {briefData.recommended_angles.map((a, i) => (
                    <li key={i} className="text-xs text-muted-foreground flex gap-1.5"><span className="text-emerald-400 shrink-0">·</span>{a}</li>
                  ))}
                </ul>
              </div>
            </div>
            {briefData.watch_out_for && (
              <div className="rounded-lg border border-orange-500/20 bg-orange-500/5 p-2.5 flex gap-2 items-start">
                <span className="text-orange-400 text-[10px] font-semibold uppercase tracking-wide shrink-0 mt-0.5">Watch out:</span>
                <p className="text-xs text-muted-foreground">{briefData.watch_out_for}</p>
              </div>
            )}
          </div>
        )}
      </section>

      {/* ── Trigger Signals ── */}
      <section className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-1.5">
          <Zap className="w-3.5 h-3.5" /> Buying Signals
        </h3>
        {signalsLoading ? (
          <div className="skeleton h-16 rounded" />
        ) : signals.length === 0 ? (
          <p className="text-xs text-muted-foreground">No trigger signals detected yet.</p>
        ) : (
          <div className="space-y-2">
            {signals.map((s) => {
              const meta = SIGNAL_LABELS[s.signal_type] ?? { label: s.signal_type, color: "text-muted-foreground bg-secondary/30 border-border" };
              return (
                <div key={s.id} className="rounded-lg border border-border p-3 space-y-1.5 text-xs">
                  <div className="flex items-center justify-between">
                    <span className={cn("text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full border", meta.color)}>{meta.label}</span>
                    <span className="text-muted-foreground">{new Date(s.triggered_at).toLocaleDateString()}</span>
                  </div>
                  {s.signal_metadata && Object.keys(s.signal_metadata).length > 0 && (
                    <div className="space-y-0.5">
                      {Object.entries(s.signal_metadata).slice(0, 3).map(([k, v]) => (
                        <p key={k} className="text-muted-foreground"><span className="capitalize">{k.replace(/_/g, " ")}: </span>{String(v)}</p>
                      ))}
                    </div>
                  )}
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Signal strength</span>
                    <span className={cn("font-mono font-semibold", scoreColorClass(s.score))}>{Math.round(s.score * 100)}%</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}

// ── IntentTab ──────────────────────────────────────────────────────────────

function IntentTab({ leadId }: { leadId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["intent", leadId],
    queryFn: () => intentApi.get(leadId),
    enabled: !!leadId,
  });

  if (isLoading) return <div className="space-y-2">{[...Array(4)].map((_, i) => <div key={i} className="skeleton h-10 rounded" />)}</div>;
  if (!data) return <p className="text-sm text-muted-foreground">No intent data yet.</p>;

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3 p-4 rounded-xl bg-violet-500/10 border border-violet-500/20">
        <Zap className="w-5 h-5 text-violet-400 shrink-0" />
        <div>
          <p className="text-xs text-muted-foreground">Total Intent Score</p>
          <p className="text-2xl font-bold text-violet-400">{Math.round(data.score * 100)}%</p>
        </div>
      </div>
      <div className="space-y-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Signals</h3>
        {data.signals.length === 0 ? (
          <p className="text-sm text-muted-foreground">No signals captured.</p>
        ) : (
          data.signals.map((s, i) => (
            <div key={i} className="flex items-center gap-3 rounded-lg px-3 py-2.5 bg-secondary/30 text-xs">
              <div className="w-1.5 h-1.5 rounded-full bg-violet-400 shrink-0" />
              <span className="flex-1 text-muted-foreground font-mono">{s.rule.replace(/_/g, " ")}</span>
              <Badge variant="secondary" className="text-[10px]">{s.triggered ? "triggered" : "inactive"}</Badge>
              <span className="font-semibold text-violet-400 w-10 text-right">+{Math.round(s.weight * 100)}%</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// ── OutreachTab ────────────────────────────────────────────────────────────

function OutreachTab({ leadId }: { leadId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["outreach", leadId],
    queryFn: () => outreachApi.list(leadId),
    enabled: !!leadId,
  });

  if (isLoading) return <div className="space-y-2">{[...Array(3)].map((_, i) => <div key={i} className="skeleton h-16 rounded" />)}</div>;

  const emails = data?.emails ?? [];

  if (!emails.length) return (
    <div className="text-center py-8">
      <Mail className="w-8 h-8 mx-auto mb-2 text-muted-foreground/30" />
      <p className="text-sm text-muted-foreground">No outreach scheduled yet.</p>
    </div>
  );

  const STATUS_ICON: Record<string, JSX.Element> = {
    sent:      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />,
    opened:    <CheckCircle2 className="w-3.5 h-3.5 text-violet-400" />,
    replied:   <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />,
    scheduled: <Clock className="w-3.5 h-3.5 text-yellow-400" />,
    failed:    <XCircle className="w-3.5 h-3.5 text-red-400" />,
  };

  return (
    <div className="space-y-3">
      {emails.map((e) => (
        <div key={e.id} className="rounded-lg border border-border p-3 space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {STATUS_ICON[e.status] ?? <Clock className="w-3.5 h-3.5 text-muted-foreground" />}
              <span className="text-xs font-medium">Step {e.step_number}</span>
            </div>
            <div className="flex items-center gap-1.5">
              {e.quality_score != null && (
                <span className={cn("text-[10px] font-mono font-semibold px-1.5 py-0.5 rounded", e.quality_score >= 7 ? "bg-emerald-500/10 text-emerald-400" : e.quality_score >= 5 ? "bg-orange-500/10 text-orange-400" : "bg-red-500/10 text-red-400")}>
                  Q:{Math.round(e.quality_score * 10)}
                </span>
              )}
              <Badge variant="secondary" className="text-[10px] capitalize">{e.status}</Badge>
            </div>
          </div>
          <p className="text-xs font-medium truncate">{e.subject}</p>
          <div className="flex gap-3 text-[10px] text-muted-foreground">
            {e.sent_at && <span>Sent {new Date(e.sent_at).toLocaleDateString()}</span>}
            {e.opened_at && <span>· Opened</span>}
            {e.replied_at && <span>· Replied</span>}
            {e.scheduled_at && !e.sent_at && <span>Scheduled {new Date(e.scheduled_at).toLocaleDateString()}</span>}
          </div>
          {e.quality_reasoning && (
            <p className="text-[10px] text-muted-foreground italic leading-relaxed border-t border-border pt-1.5">{e.quality_reasoning}</p>
          )}
          {e.quality_flags && Object.keys(e.quality_flags).length > 0 && (
            <div className="flex flex-wrap gap-1">
              {Object.entries(e.quality_flags).map(([dim, score]) => (
                <span key={dim} className={cn("text-[9px] px-1.5 py-0.5 rounded-full border capitalize", (score as number) >= 7 ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" : "bg-orange-500/10 text-orange-400 border-orange-500/20")}>
                  {dim}: {Math.round((score as number) * 10) / 10}
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── ActivityTab ────────────────────────────────────────────────────────────

function ActivityTab({ leadId }: { leadId: string }) {
  const { data: convData, isLoading: convLoading } = useQuery({
    queryKey: ["conversations", leadId],
    queryFn: () => conversationsApi.list(leadId),
    enabled: !!leadId,
  });
  const { data: bookingData, isLoading: bookingLoading } = useQuery({
    queryKey: ["bookings", leadId],
    queryFn: () => bookingApi.list(leadId),
    enabled: !!leadId,
  });

  const convs = convData?.conversations ?? [];
  const bookings = bookingData?.bookings ?? [];

  return (
    <div className="space-y-5">
      <section className="space-y-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-1.5">
          <Calendar className="w-3.5 h-3.5" /> Booking Requests
        </h3>
        {bookingLoading ? <div className="skeleton h-14 rounded" /> : bookings.length === 0 ? (
          <p className="text-xs text-muted-foreground">No bookings yet.</p>
        ) : (
          bookings.map((b) => (
            <div key={b.id} className="rounded-lg border border-border p-3 text-xs space-y-1">
              <div className="flex items-center justify-between">
                <span className="font-medium capitalize">{b.status}</span>
                {b.scheduling_url && (
                  <a href={b.scheduling_url} target="_blank" rel="noreferrer" className="text-violet-400 hover:underline text-[10px]">Cal link ↗</a>
                )}
              </div>
              {b.meeting_time && <p className="text-muted-foreground">Meeting: {new Date(b.meeting_time).toLocaleString()}</p>}
              <p className="text-muted-foreground">Created {new Date(b.created_at).toLocaleDateString()}</p>
            </div>
          ))
        )}
      </section>
      <section className="space-y-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-1.5">
          <MessageSquare className="w-3.5 h-3.5" /> Conversations
        </h3>
        {convLoading ? <div className="skeleton h-24 rounded" /> : convs.length === 0 ? (
          <p className="text-xs text-muted-foreground">No conversations yet.</p>
        ) : (
          convs.map((c) => (
            <div key={c.id} className="rounded-lg border border-border p-3 space-y-2">
              <div className="flex items-center justify-between text-xs">
                <Badge variant="secondary" className="text-[10px] capitalize">{c.channel}</Badge>
                <span className="text-muted-foreground">{c.messages?.length ?? 0} messages</span>
              </div>
              {c.summary && <p className="text-xs text-muted-foreground italic leading-relaxed">{c.summary}</p>}
              {c.messages?.slice(-2).map((m: { role: string; content?: string }, i: number) => (
                <div key={i} className={cn("text-[10px] rounded px-2 py-1.5", m.role === "assistant" ? "bg-violet-500/10 text-violet-300" : "bg-secondary/50 text-foreground")}>
                  <span className="font-semibold capitalize">{m.role}: </span>
                  <span className="text-muted-foreground">{m.content?.slice(0, 100)}{(m.content?.length ?? 0) > 100 ? "…" : ""}</span>
                </div>
              ))}
            </div>
          ))
        )}
      </section>
    </div>
  );
}

// ── TraceTab ───────────────────────────────────────────────────────────────

function TraceTab({ leadId }: { leadId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["pipeline-trace", leadId],
    queryFn: () => pipelineApi.trace(leadId),
    enabled: !!leadId,
  });

  if (isLoading) return <div className="space-y-2">{[...Array(5)].map((_, i) => <div key={i} className="skeleton h-10 rounded" />)}</div>;
  if (!data || !data.agent_logs?.length) return (
    <div className="text-center py-8">
      <GitBranch className="w-8 h-8 mx-auto mb-2 text-muted-foreground/30" />
      <p className="text-sm text-muted-foreground">No pipeline trace available yet.</p>
    </div>
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        {(data.nodes_executed ?? []).map((n) => (
          <span key={n} className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">{n}</span>
        ))}
      </div>
      <div className="space-y-1.5">
        {data.agent_logs.map((log) => (
          <div key={log.id} className="flex items-center gap-3 rounded-lg px-3 py-2 bg-secondary/30 text-xs">
            {log.status === "success"
              ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
              : <XCircle className="w-3.5 h-3.5 text-red-400 shrink-0" />}
            <span className="font-mono font-medium w-28 shrink-0">{log.agent_name}</span>
            <span className="text-muted-foreground flex-1 truncate">{log.error_message ?? log.status}</span>
            {log.duration_ms != null && <span className="text-muted-foreground shrink-0">{log.duration_ms}ms</span>}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── LeadDetailPanel ────────────────────────────────────────────────────────

const VERIFICATION_BADGE: Record<string, { variant: "success" | "warning" | "destructive" | "secondary"; label: string }> = {
  valid: { variant: "success", label: "deliverable" },
  risky: { variant: "warning", label: "risky address" },
  undeliverable: { variant: "destructive", label: "undeliverable" },
  unknown: { variant: "secondary", label: "unverified" },
};

function EmailVerificationBadge({ lead }: { lead: LeadDetail }) {
  if (!lead.email_verification_status) return null;
  const meta = VERIFICATION_BADGE[lead.email_verification_status];
  if (!meta) return null;
  return (
    <Badge
      variant={meta.variant}
      className="text-[10px] shrink-0"
      title={lead.email_verification_reason ?? undefined}
    >
      {meta.label}
    </Badge>
  );
}

function LeadDetailPanel({ lead, onClose }: { lead: LeadDetail; onClose: () => void }) {
  const [activeTab, setActiveTab] = useState<TabId>("profile");

  return (
    <div className="fixed inset-y-0 right-0 z-40 w-[520px] bg-card border-l border-border shadow-2xl flex flex-col animate-slide-in">
      <div className="flex items-center justify-between px-6 py-4 border-b border-border">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-gradient-to-br from-violet-600 to-indigo-600 flex items-center justify-center text-white font-semibold shrink-0">
            {lead.name.slice(0, 2).toUpperCase()}
          </div>
          <div>
            <h2 className="font-semibold leading-tight">{lead.name}</h2>
            <div className="flex items-center gap-1.5">
              <p className="text-xs text-muted-foreground">{lead.email} · {lead.company}</p>
              <EmailVerificationBadge lead={lead} />
            </div>
          </div>
        </div>
        <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-secondary transition-colors">
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="flex border-b border-border px-3">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setActiveTab(id)}
            className={cn(
              "flex items-center gap-1.5 px-3 py-2.5 text-xs font-medium border-b-2 transition-colors",
              activeTab === id ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            <Icon className="w-3.5 h-3.5" />
            {label}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto p-5">
        {activeTab === "profile"  && <ProfileTab lead={lead} />}
        {activeTab === "intel"    && <IntelTab leadId={lead.id} />}
        {activeTab === "intent"   && <IntentTab leadId={lead.id} />}
        {activeTab === "outreach" && <OutreachTab leadId={lead.id} />}
        {activeTab === "activity" && <ActivityTab leadId={lead.id} />}
        {activeTab === "trace"    && <TraceTab leadId={lead.id} />}
      </div>
    </div>
  );
}

// ── Main Leads page ────────────────────────────────────────────────────────

export default function Leads() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [selectedLead, setSelectedLead] = useState<LeadDetail | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [page, setPage] = useState(0);
  const [semanticMode, setSemanticMode] = useState(false);
  const [semanticQuery, setSemanticQuery] = useState("");
  const [kbIndex, setKbIndex] = useState(-1);
  const [showCheatsheet, setShowCheatsheet] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const PAGE_SIZE = 50;

  const { data: leads = [], isLoading } = useQuery({
    queryKey: ["leads", page],
    queryFn: () => leadsApi.list(page * PAGE_SIZE, PAGE_SIZE),
    refetchInterval: 15_000,
  });

  const { mutate: loadDetail } = useMutation({
    mutationFn: leadsApi.get,
    onSuccess: (d) => setSelectedLead(d),
  });

  const { mutate: archive } = useMutation({
    mutationFn: (ids: string[]) => leadsApi.batch("archive", ids),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["leads"] }); toast.success("Leads archived"); setSelectedIds(new Set()); },
  });

  const { mutate: deleteBatch } = useMutation({
    mutationFn: (ids: string[]) => leadsApi.batch("delete", ids),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["leads"] }); toast.success("Leads deleted"); setSelectedIds(new Set()); },
  });

  const { mutate: reprocessFailed, isPending: reprocessing } = useMutation({
    mutationFn: leadsApi.reprocessFailed,
    onSuccess: (d) => { qc.invalidateQueries({ queryKey: ["leads"] }); toast.success(`${d.requeued} failed leads re-queued`); },
    onError: () => toast.error("Failed to reprocess leads"),
  });

  const { data: coolingData } = useQuery({
    queryKey: ["cooling"],
    queryFn: () => decayApi.cooling(100),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
  const coolingSet = new Set((coolingData?.leads ?? []).map((l) => l.id));
  const coolingMap = new Map((coolingData?.leads ?? []).map((l) => [l.id, l.decay]));

  const { data: semanticResults, isFetching: semanticFetching } = useQuery({
    queryKey: ["semantic-search", semanticQuery],
    queryFn: () => analyticsApi.semanticSearch(semanticQuery, 20),
    enabled: semanticMode && semanticQuery.length >= 3,
    staleTime: 30_000,
  });

  const failedCount = leads.filter((l) => l.status === "failed").length;

  const filtered = leads.filter((l) => {
    const q = search.toLowerCase();
    const matchSearch = !q || l.name.toLowerCase().includes(q) || l.email.toLowerCase().includes(q) || l.company.toLowerCase().includes(q);
    const matchStatus = statusFilter === "all" || l.status === statusFilter;
    return matchSearch && matchStatus && !l.archived;
  });

  const toggleSelect = (id: string) => {
    const next = new Set(selectedIds);
    if (next.has(id)) { next.delete(id); } else { next.add(id); }
    setSelectedIds(next);
  };

  const handleExport = async () => {
    try {
      const blob = await leadsApi.export("csv");
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = "leads.csv"; a.click();
      URL.revokeObjectURL(url);
    } catch { toast.error("Export failed"); }
  };

  // Keyboard shortcut hook — must come after filtered and loadDetail
  useKeyboardShortcuts({
    leads: filtered,
    selectedIndex: kbIndex,
    onSelectIndex: setKbIndex,
    onOpenLead: (id) => loadDetail(id),
    onClose: () => { setSelectedLead(null); setKbIndex(-1); },
    onFocusSearch: () => { searchInputRef.current?.focus(); },
    onToggleCheatsheet: () => setShowCheatsheet((v) => !v),
  });

  return (
    <div className="flex flex-col min-h-screen">
      <Header
        title="Leads"
        subtitle={`${filtered.length} leads`}
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowCheatsheet(true)}
              title="Keyboard shortcuts (?)"
              className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
            >
              <Keyboard className="w-4 h-4" />
            </button>
            {failedCount > 0 && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => reprocessFailed()}
                loading={reprocessing}
                className="gap-2 border-red-500/30 text-red-400 hover:bg-red-500/10 hover:text-red-400"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                Reprocess {failedCount} failed
              </Button>
            )}
            <Button variant="gradient" size="sm" onClick={handleExport} className="gap-2">
              <Download className="w-3.5 h-3.5" />
              Export CSV
            </Button>
          </div>
        }
      />

      <div className="flex-1 p-8 animate-fade-in">
        {/* Search + filters */}
        <div className="flex gap-3 mb-6">
          {semanticMode ? (
            <form
              className="flex flex-1 gap-2"
              onSubmit={(e) => { e.preventDefault(); const fd = new FormData(e.currentTarget); setSemanticQuery((fd.get("q") as string) ?? ""); }}
            >
              <div className="relative flex-1">
                <Sparkles className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-violet-400" />
                <Input
                  name="q"
                  placeholder='e.g. "leads who mentioned pricing concerns"'
                  defaultValue={semanticQuery}
                  className="pl-9 border-violet-500/40 focus-visible:ring-violet-500/40"
                />
              </div>
              <Button type="submit" variant="gradient" size="sm" loading={semanticFetching} className="gap-1.5">
                <Search className="w-3.5 h-3.5" /> Search
              </Button>
            </form>
          ) : (
            <>
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  ref={searchInputRef}
                  placeholder="Search by name, email or company… (press / to focus)"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="pl-9"
                />
              </div>
              <Select value={statusFilter} onValueChange={setStatusFilter}>
                <SelectTrigger className="w-[140px]">
                  <Filter className="w-3.5 h-3.5 mr-1.5" />
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Status</SelectItem>
                  <SelectItem value="complete">Complete</SelectItem>
                  <SelectItem value="processing">Processing</SelectItem>
                  <SelectItem value="pending">Pending</SelectItem>
                  <SelectItem value="failed">Failed</SelectItem>
                </SelectContent>
              </Select>
            </>
          )}
          <Button
            variant={semanticMode ? "default" : "outline"}
            size="sm"
            onClick={() => { setSemanticMode((m) => !m); setSemanticQuery(""); }}
            className={`gap-1.5 shrink-0 ${semanticMode ? "bg-violet-600 hover:bg-violet-700" : ""}`}
            title="AI semantic search over conversation history"
          >
            <Sparkles className="w-3.5 h-3.5" />
            AI Search
          </Button>
        </div>

        {/* Semantic results */}
        {semanticMode && (
          <div className="mb-6">
            {!semanticQuery ? (
              <div className="rounded-xl border border-violet-500/20 bg-violet-500/5 p-6 text-center">
                <Sparkles className="w-6 h-6 text-violet-400 mx-auto mb-2" />
                <p className="text-sm font-medium mb-1">Search conversations by meaning</p>
                <p className="text-xs text-muted-foreground">
                  Try: "leads who mentioned pricing" · "prospects with Q1 budget" · "companies evaluating competitors"
                </p>
              </div>
            ) : semanticFetching ? (
              <div className="space-y-2">{[...Array(4)].map((_, i) => <div key={i} className="skeleton h-14 rounded-lg" />)}</div>
            ) : (semanticResults?.results ?? []).length === 0 ? (
              <div className="text-center py-8 text-sm text-muted-foreground">No conversations matched — try a different query</div>
            ) : (
              <Card className="overflow-hidden">
                <div className="px-4 py-3 border-b border-border flex items-center justify-between">
                  <p className="text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">{semanticResults?.count ?? 0}</span> conversations matched
                  </p>
                  <p className="text-xs text-muted-foreground">Sorted by semantic similarity</p>
                </div>
                <div className="divide-y divide-border">
                  {(semanticResults?.results ?? []).map((r) => (
                    <div
                      key={r.conversation_id}
                      className="flex items-start gap-4 px-4 py-3 hover:bg-secondary/20 cursor-pointer transition-colors"
                      onClick={() => loadDetail(r.lead_id)}
                    >
                      <div className="w-7 h-7 rounded-full bg-gradient-to-br from-violet-600/60 to-indigo-600/60 flex items-center justify-center text-[10px] font-semibold text-white shrink-0 mt-0.5">
                        {r.lead_name.slice(0, 2).toUpperCase()}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-0.5">
                          <span className="text-sm font-medium">{r.lead_name}</span>
                          <Badge variant="secondary" className="text-[10px] capitalize">{r.channel}</Badge>
                        </div>
                        <p className="text-xs text-muted-foreground line-clamp-2">{r.snippet}</p>
                      </div>
                      <div className="shrink-0 text-right">
                        <p className="text-sm font-semibold text-violet-400">
                          {r.similarity != null ? `${Math.round(r.similarity * 100)}%` : "—"}
                        </p>
                        <p className="text-[10px] text-muted-foreground">match</p>
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            )}
          </div>
        )}

        {/* Bulk actions */}
        {selectedIds.size > 0 && (
          <div className="flex items-center gap-3 mb-4 p-3 rounded-lg bg-primary/10 border border-primary/20 animate-fade-in">
            <span className="text-sm font-medium">{selectedIds.size} selected</span>
            <Button size="sm" variant="outline" onClick={() => archive([...selectedIds])} className="gap-1.5">
              <Archive className="w-3.5 h-3.5" /> Archive
            </Button>
            <Button size="sm" variant="destructive" onClick={() => deleteBatch([...selectedIds])} className="gap-1.5">
              <Trash2 className="w-3.5 h-3.5" /> Delete
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSelectedIds(new Set())}>Clear</Button>
          </div>
        )}

        {/* Table */}
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-secondary/30">
                  <th className="w-10 p-3">
                    <input
                      type="checkbox"
                      className="rounded border-border bg-transparent accent-primary"
                      checked={selectedIds.size === filtered.length && filtered.length > 0}
                      onChange={(e) => setSelectedIds(e.target.checked ? new Set(filtered.map((l) => l.id)) : new Set())}
                    />
                  </th>
                  {["Name", "Company", "Status", "Verdict", "Lookalike", "Quality", "Created", ""].map((h) => (
                    <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-muted-foreground uppercase tracking-wide">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {isLoading ? (
                  [...Array(8)].map((_, i) => (
                    <tr key={i} className="border-b border-border/50">
                      <td colSpan={9} className="p-3"><div className="skeleton h-9 rounded" /></td>
                    </tr>
                  ))
                ) : filtered.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="p-12 text-center text-muted-foreground">No leads found</td>
                  </tr>
                ) : (
                  filtered.map((lead, idx) => (
                    <tr
                      key={lead.id}
                      className={cn(
                        "border-b border-border/50 hover:bg-secondary/20 transition-colors group cursor-pointer",
                        idx === kbIndex && "bg-violet-500/10 ring-1 ring-inset ring-violet-500/30"
                      )}
                      onClick={() => { setKbIndex(idx); loadDetail(lead.id); }}
                    >
                      <td className="p-3" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          className="rounded border-border bg-transparent accent-primary"
                          checked={selectedIds.has(lead.id)}
                          onChange={() => toggleSelect(lead.id)}
                        />
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2.5">
                          <div className="w-7 h-7 rounded-full bg-gradient-to-br from-violet-600/60 to-indigo-600/60 flex items-center justify-center text-[10px] font-semibold text-white shrink-0">
                            {lead.name.slice(0, 2).toUpperCase()}
                          </div>
                          <div>
                            <p className="font-medium">{lead.name}</p>
                            <p className="text-xs text-muted-foreground">{lead.email}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5 text-muted-foreground">
                          <Building2 className="w-3.5 h-3.5 shrink-0" />
                          <span>{lead.company}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant={STATUS_COLORS[lead.status] as Parameters<typeof Badge>[0]["variant"]} className="capitalize">
                          {lead.status}
                        </Badge>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5">
                          <VerdictBadge verdict={lead.final_verdict} />
                          {coolingSet.has(lead.id) && (() => {
                            const decay = coolingMap.get(lead.id);
                            if (!decay) return null;
                            const urgent = decay.urgency === "urgent";
                            return (
                              <span
                                title={`${decay.days_since_engagement}d without engagement`}
                                className={cn(
                                  "inline-flex items-center gap-0.5 text-[10px] font-medium px-1.5 py-0.5 rounded-full border",
                                  urgent
                                    ? "border-red-500/40 bg-red-500/10 text-red-400"
                                    : "border-orange-500/40 bg-orange-500/10 text-orange-400"
                                )}
                              >
                                <Timer className="w-2.5 h-2.5" />
                                {decay.days_since_engagement}d
                              </span>
                            );
                          })()}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        {lead.lookalike_score != null ? (
                          <div className="flex items-center gap-2">
                            <div className="w-16 h-1.5 rounded-full bg-secondary overflow-hidden">
                              <div
                                className={cn("h-full rounded-full transition-all", lead.lookalike_score >= 0.7 ? "bg-emerald-500" : lead.lookalike_score >= 0.4 ? "bg-orange-400" : "bg-red-500")}
                                style={{ width: `${Math.round(lead.lookalike_score * 100)}%` }}
                              />
                            </div>
                            <span className={cn("text-xs font-mono font-semibold tabular-nums", scoreColorClass(lead.lookalike_score))}>
                              {Math.round(lead.lookalike_score * 100)}%
                            </span>
                          </div>
                        ) : (
                          <span className="text-xs text-muted-foreground/40">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className={cn("font-semibold", scoreColor(lead.data_quality_score))}>
                          {lead.data_quality_score != null ? Math.round(lead.data_quality_score * 100) : "—"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground text-xs">{formatDate(lead.created_at)}</td>
                      <td className="px-4 py-3">
                        <ChevronRight className="w-4 h-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </Card>

        {/* Pagination */}
        <div className="flex items-center justify-between mt-4 text-sm text-muted-foreground">
          <span>Showing {filtered.length} leads · press <kbd className="px-1 py-0.5 text-[10px] rounded border border-border font-mono">?</kbd> for shortcuts</span>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Prev</Button>
            <Button size="sm" variant="outline" disabled={leads.length < PAGE_SIZE} onClick={() => setPage((p) => p + 1)}>Next</Button>
          </div>
        </div>
      </div>

      {/* Keyboard cheatsheet modal */}
      <Dialog open={showCheatsheet} onOpenChange={setShowCheatsheet}>
        <DialogContent className="sm:max-w-xs">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-sm">
              <Keyboard className="w-4 h-4 text-violet-400" />
              Keyboard Shortcuts
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-2 pt-1">
            {SHORTCUTS.map(({ keys, label }) => (
              <div key={label} className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">{label}</span>
                <div className="flex items-center gap-1">
                  {keys.map((k) => (
                    <kbd key={k} className="px-2 py-0.5 text-xs rounded border border-border font-mono bg-secondary">
                      {k}
                    </kbd>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>

      {/* Detail panel overlay */}
      {selectedLead && (
        <>
          <div className="fixed inset-0 z-30 bg-black/40 backdrop-blur-sm" onClick={() => setSelectedLead(null)} />
          <LeadDetailPanel lead={selectedLead} onClose={() => setSelectedLead(null)} />
        </>
      )}
    </div>
  );
}
