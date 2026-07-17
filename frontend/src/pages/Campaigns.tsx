import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Flag, Bot, ShieldCheck, Plus, CheckCircle2, XCircle, RefreshCw, FileText,
  PauseCircle, PlayCircle, Sparkles, Gauge, Users2, TrendingUp, AlertTriangle, CalendarRange,
} from "lucide-react";
import { toast } from "sonner";
import {
  campaignsApi,
  type Campaign, type CampaignAction, type CampaignAutonomyMode, type CampaignPlan,
} from "../lib/api";
import { Header } from "../components/layout/Header";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "../components/ui/dialog";
import { cn, formatDateShort, apiErrorMessage } from "../lib/utils";
import { useAuthStore } from "../store/authStore";

const GOAL_LABEL: Record<Campaign["goal_type"], string> = {
  meetings: "meetings booked",
  replies: "replies",
  qualified_leads: "leads qualified",
};

// ── Strategy autonomy dial ────────────────────────────────────────────────────

function StrategyAutonomyDial() {
  const qc = useQueryClient();
  const { isManager } = useAuthStore();
  const { data } = useQuery({ queryKey: ["campaign-autonomy"], queryFn: campaignsApi.getAutonomy });

  const { mutate: setMode } = useMutation({
    mutationFn: campaignsApi.setAutonomy,
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["campaign-autonomy"] });
      toast.success(res.mode === "auto"
        ? "Plans now execute automatically"
        : "Plans now wait for your approval");
    },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, "Failed to change mode")),
  });

  const modes: { mode: CampaignAutonomyMode; label: string; hint: string; icon: typeof Bot }[] = [
    { mode: "approve", label: "Approve plans", hint: "Every strategy change waits for a human", icon: ShieldCheck },
    { mode: "auto", label: "Full auto", hint: "The agent applies its own plans on schedule", icon: Bot },
  ];

  return (
    <Card>
      <CardContent className="p-4 flex items-center gap-4">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold">Strategy autonomy</p>
          <p className="text-xs text-muted-foreground">
            The email dial governs what gets sent; this one governs how the agent changes strategy.
          </p>
        </div>
        <div className="flex gap-2">
          {modes.map(({ mode, label, hint, icon: Icon }) => {
            const active = data?.mode === mode;
            return (
              <button
                key={mode}
                disabled={!isManager()}
                title={hint}
                onClick={() => setMode(mode)}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-2 rounded-lg border text-xs font-medium transition-colors",
                  active ? "border-violet-500 bg-violet-500/10 text-foreground" : "border-border text-muted-foreground hover:bg-secondary/40",
                  !isManager() && "opacity-60 cursor-not-allowed"
                )}
              >
                <Icon className={cn("w-3.5 h-3.5", active && "text-violet-400")} />
                {label}
              </button>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

// ── Create dialog ─────────────────────────────────────────────────────────────

function CreateCampaignDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [goalType, setGoalType] = useState<Campaign["goal_type"]>("meetings");
  const [target, setTarget] = useState(10);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [maxDaily, setMaxDaily] = useState<number | "">("");
  const [industry, setIndustry] = useState("");

  const { mutate: create, isPending } = useMutation({
    mutationFn: () =>
      campaignsApi.create({
        name,
        goal_type: goalType,
        goal_target: target,
        period_start: `${start}T00:00:00`,
        period_end: `${end}T23:59:59`,
        constraints: {
          ...(maxDaily !== "" ? { max_daily_sends: Number(maxDaily) } : {}),
          ...(industry.trim() ? { segments: [{ industry: industry.trim() }] } : {}),
        },
      }),
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      onOpenChange(false);
      toast.success(`"${c.name}" created — the agent plans against it daily`);
    },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, "Failed to create campaign")),
  });

  const valid = name.trim() && target >= 1 && start && end && end > start;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Give the agent a quota</DialogTitle>
          <DialogDescription>
            A goal, a deadline, and constraints — the agent plans, acts, and reports against it.
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4 mt-2"
          onSubmit={(e) => { e.preventDefault(); if (valid) create(); }}
        >
          <div className="space-y-2">
            <Label>Campaign name</Label>
            <Input placeholder="Q3 meetings push" value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label>Goal</Label>
              <select
                aria-label="Goal type"
                className="w-full h-9 rounded-md border border-input bg-transparent px-3 text-sm"
                value={goalType}
                onChange={(e) => setGoalType(e.target.value as Campaign["goal_type"])}
              >
                <option value="meetings">Meetings booked</option>
                <option value="replies">Replies</option>
                <option value="qualified_leads">Leads qualified</option>
              </select>
            </div>
            <div className="space-y-2">
              <Label>Target</Label>
              <Input type="number" min={1} value={target}
                     onChange={(e) => setTarget(Number(e.target.value))} aria-label="Goal target" />
            </div>
            <div className="space-y-2">
              <Label>Start</Label>
              <Input type="date" value={start} onChange={(e) => setStart(e.target.value)} aria-label="Period start" required />
            </div>
            <div className="space-y-2">
              <Label>End</Label>
              <Input type="date" value={end} onChange={(e) => setEnd(e.target.value)} aria-label="Period end" required />
            </div>
            <div className="space-y-2">
              <Label>Max sends / day (optional)</Label>
              <Input type="number" min={1} value={maxDaily}
                     onChange={(e) => setMaxDaily(e.target.value === "" ? "" : Number(e.target.value))} />
            </div>
            <div className="space-y-2">
              <Label>Target industry (optional)</Label>
              <Input placeholder="SaaS" value={industry} onChange={(e) => setIndustry(e.target.value)} />
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" variant="gradient" loading={isPending} disabled={!valid}>Create campaign</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ── Plan rendering ────────────────────────────────────────────────────────────

function describeAction(action: CampaignAction): string {
  switch (action.type) {
    case "pause_sequence": return `Pause sequence — ${action.reason ?? ""}`;
    case "resume_sequence": return `Resume sequence — ${action.reason ?? ""}`;
    case "create_variant": return `New variant: ${action.angle ?? ""} (${action.draft_steps?.length ?? 0} step(s))`;
    case "adjust_daily_target": return `Set daily send target to ${action.value} — ${action.reason ?? ""}`;
    case "request_prospecting": return `Source ${action.count} new leads (${JSON.stringify(action.segment ?? {})}) — ${action.reason ?? ""}`;
    case "escalate": return `Escalate (${action.severity}): ${action.message ?? ""}`;
    default: return action.type;
  }
}

const ACTION_ICON: Record<string, typeof Sparkles> = {
  pause_sequence: PauseCircle,
  resume_sequence: PlayCircle,
  create_variant: Sparkles,
  adjust_daily_target: Gauge,
  request_prospecting: Users2,
  escalate: AlertTriangle,
};

function PlanCard({ campaign, plan }: { campaign: Campaign; plan: CampaignPlan }) {
  const qc = useQueryClient();
  const { isManager } = useAuthStore();
  const invalidate = () => qc.invalidateQueries({ queryKey: ["campaigns"] });

  const { mutate: approve, isPending: approving } = useMutation({
    mutationFn: () => campaignsApi.approvePlan(campaign.id, plan.id),
    onSuccess: (res) => {
      invalidate();
      toast.success(`Plan applied — ${res.execution.succeeded} action(s) executed`);
    },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, "Approval failed")),
  });

  const { mutate: reject, isPending: rejecting } = useMutation({
    mutationFn: () => {
      const reason = window.prompt("Why reject? (optional)") ?? undefined;
      return campaignsApi.rejectPlan(campaign.id, plan.id, reason);
    },
    onSuccess: () => { invalidate(); toast.success("Plan rejected"); },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, "Rejection failed")),
  });

  const pending = plan.status === "pending_approval";

  return (
    <div className={cn("rounded-lg border p-3 space-y-2",
      pending ? "border-violet-500/50 bg-violet-500/5" : "border-border")}>
      <div className="flex items-center gap-2">
        <Bot className="w-3.5 h-3.5 text-violet-400 shrink-0" />
        <span className="text-xs font-semibold">Agent plan v{plan.version}</span>
        <Badge
          variant={pending ? "warning" : plan.status === "active" ? "success" : "secondary"}
          className="text-[10px]"
        >
          {plan.status.replace("_", " ")}
        </Badge>
        <span className="text-[11px] text-muted-foreground ml-auto">{formatDateShort(plan.generated_at)}</span>
      </div>

      {plan.diagnosis && (
        <p className="text-xs text-muted-foreground leading-relaxed whitespace-pre-wrap">{plan.diagnosis}</p>
      )}

      {plan.actions.length > 0 ? (
        <ul className="space-y-1.5">
          {plan.actions.map((action, i) => {
            const Icon = ACTION_ICON[action.type] ?? Sparkles;
            const logEntry = plan.execution_log?.[i];
            return (
              <li key={i} className="flex items-start gap-2 text-xs">
                <Icon className="w-3.5 h-3.5 text-muted-foreground shrink-0 mt-0.5" />
                <span className="flex-1">{describeAction(action)}</span>
                {logEntry && (
                  logEntry.success
                    ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" aria-label="Executed" />
                    : <XCircle className="w-3.5 h-3.5 text-red-400 shrink-0" aria-label="Failed" />
                )}
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="text-xs text-muted-foreground italic">No changes proposed — holding course.</p>
      )}

      {pending && isManager() && (
        <div className="flex items-center gap-2 pt-1">
          <Button size="sm" variant="gradient" loading={approving} onClick={() => approve()} className="gap-1.5">
            <CheckCircle2 className="w-3.5 h-3.5" />
            Approve & execute
          </Button>
          <Button size="sm" variant="ghost" loading={rejecting} onClick={() => reject()}
                  className="text-red-400 hover:text-red-400 hover:bg-red-500/10 gap-1.5">
            <XCircle className="w-3.5 h-3.5" />
            Reject
          </Button>
        </div>
      )}
    </div>
  );
}

// ── Campaign card ─────────────────────────────────────────────────────────────

function PaceMeter({ campaign }: { campaign: Campaign }) {
  const { pace } = campaign;
  const pct = Math.min(100, Math.round((pace.actual / Math.max(1, campaign.goal_target)) * 100));
  const expectedPct = pace.expected_by_now != null
    ? Math.min(100, Math.round((pace.expected_by_now / Math.max(1, campaign.goal_target)) * 100))
    : null;
  const behind = pace.pace_ratio != null && pace.pace_ratio < 0.85;

  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-bold tracking-tight">{pace.actual}</span>
        <span className="text-sm text-muted-foreground">/ {campaign.goal_target} {GOAL_LABEL[campaign.goal_type]}</span>
        {pace.pace_ratio != null && (
          <Badge variant={behind ? "warning" : "success"} className="text-[10px] ml-auto gap-1">
            <TrendingUp className="w-2.5 h-2.5" />
            pace ×{pace.pace_ratio}
          </Badge>
        )}
      </div>
      <div className="relative h-2 rounded-full bg-secondary overflow-hidden">
        <div
          className={cn("h-full rounded-full", behind ? "bg-yellow-500" : "bg-emerald-500")}
          style={{ width: `${pct}%` }}
        />
        {expectedPct != null && (
          <div
            className="absolute top-0 h-full w-0.5 bg-foreground/70"
            style={{ left: `${expectedPct}%` }}
            title={`Expected by now: ${pace.expected_by_now}`}
          />
        )}
      </div>
      <p className="text-[11px] text-muted-foreground">
        {pace.expected_by_now != null ? `Expected ${pace.expected_by_now} by now · ` : ""}
        projected {pace.projected_end_total ?? "—"} by {formatDateShort(campaign.period_end)}
        {" · "}{pace.elapsed_weekdays}/{pace.total_weekdays} working days elapsed
      </p>
    </div>
  );
}

function CampaignCard({ summary }: { summary: Campaign }) {
  const qc = useQueryClient();
  const { isManager } = useAuthStore();
  const [reportOpen, setReportOpen] = useState(false);

  const { data: campaign } = useQuery({
    queryKey: ["campaign", summary.id],
    queryFn: () => campaignsApi.get(summary.id),
    initialData: summary,
  });

  const { data: report } = useQuery({
    queryKey: ["campaign-report", summary.id],
    queryFn: () => campaignsApi.report(summary.id),
    enabled: reportOpen,
  });

  const { mutate: replan, isPending: replanning } = useMutation({
    mutationFn: () => campaignsApi.replan(summary.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      qc.invalidateQueries({ queryKey: ["campaign", summary.id] });
      toast.success("Agent produced a fresh plan");
    },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, "Replan failed")),
  });

  const c = campaign ?? summary;
  const totals = c.progress?.total;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-violet-500/10">
            <Flag className="w-4 h-4 text-violet-400" />
          </div>
          <div className="min-w-0 flex-1">
            <CardTitle className="text-sm truncate">{c.name}</CardTitle>
            <CardDescription className="flex items-center gap-1.5">
              <CalendarRange className="w-3 h-3" />
              {formatDateShort(c.period_start)} → {formatDateShort(c.period_end)}
            </CardDescription>
          </div>
          <Badge variant={c.status === "active" ? "success" : c.status === "paused" ? "warning" : "secondary"}>
            {c.status}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <PaceMeter campaign={c} />

        {totals && (
          <div className="grid grid-cols-4 gap-2 text-center">
            {[
              { label: "Sent", value: totals.sends },
              { label: "Replies", value: totals.replies },
              { label: "Bounces", value: totals.bounces },
              { label: "LLM spend", value: `$${totals.spend_usd}` },
            ].map(({ label, value }) => (
              <div key={label} className="rounded-lg bg-secondary/40 py-2">
                <p className="text-sm font-semibold">{value}</p>
                <p className="text-[10px] text-muted-foreground uppercase tracking-wide">{label}</p>
              </div>
            ))}
          </div>
        )}

        {c.current_plan && <PlanCard campaign={c} plan={c.current_plan} />}

        <div className="flex items-center gap-2">
          {isManager() && c.status === "active" && (
            <Button size="sm" variant="outline" loading={replanning} onClick={() => replan()} className="gap-1.5">
              <RefreshCw className="w-3.5 h-3.5" />
              Replan now
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => setReportOpen(true)} className="gap-1.5 text-muted-foreground">
            <FileText className="w-3.5 h-3.5" />
            Agent report
          </Button>
        </div>
      </CardContent>

      <Dialog open={reportOpen} onOpenChange={setReportOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Agent report — {c.name}</DialogTitle>
            <DialogDescription>Written by the campaign agent from its own action log and metrics</DialogDescription>
          </DialogHeader>
          <pre className="text-xs whitespace-pre-wrap font-sans leading-relaxed max-h-[420px] overflow-y-auto rounded-lg bg-secondary/40 border border-border p-4">
            {report?.report_md ?? "Generating…"}
          </pre>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Campaigns() {
  const { isManager } = useAuthStore();
  const [createOpen, setCreateOpen] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["campaigns"],
    queryFn: campaignsApi.list,
    refetchInterval: 60_000,
  });

  return (
    <div className="flex flex-col min-h-screen">
      <Header
        title="Campaigns"
        subtitle="Hand the agent a quota — it plans, acts, and explains itself"
        actions={
          isManager() ? (
            <Button size="sm" variant="gradient" onClick={() => setCreateOpen(true)} className="gap-1.5">
              <Plus className="w-3.5 h-3.5" />
              New campaign
            </Button>
          ) : undefined
        }
      />
      <div className="flex-1 p-8 space-y-6 max-w-5xl animate-fade-in">
        <StrategyAutonomyDial />

        {isLoading ? (
          <p className="text-sm text-muted-foreground py-8 text-center">Loading…</p>
        ) : (data?.campaigns.length ?? 0) === 0 ? (
          <Card>
            <CardContent className="py-12 text-center">
              <Flag className="w-8 h-8 text-muted-foreground mx-auto mb-3" />
              <p className="text-sm font-medium">No campaigns yet</p>
              <p className="text-xs text-muted-foreground mt-1 max-w-md mx-auto">
                Create one to put the agent on a quota: it reviews progress daily, pauses weak
                sequences, drafts new variants, tops up the pipeline, and reports back.
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
            {data!.campaigns.map((c) => (
              <CampaignCard key={c.id} summary={c} />
            ))}
          </div>
        )}
      </div>

      <CreateCampaignDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}
