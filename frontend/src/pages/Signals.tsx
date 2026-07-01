import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Radio, RefreshCw, Building2, Send, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import { signalApi, outreachApi } from "../lib/api";
import type { TriggerSignalType } from "../types";
import { Header } from "../components/layout/Header";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { cn } from "../lib/utils";

const SIGNAL_META: Record<TriggerSignalType, { label: string; description: string; colorClass: string }> = {
  funding_trigger:     { label: "Funding Round",  description: "Company received new funding",     colorClass: "text-emerald-400 bg-emerald-500/10 border-emerald-500/30" },
  job_posting_trigger: { label: "Hiring Signal",  description: "Company is actively hiring",       colorClass: "text-blue-400 bg-blue-500/10 border-blue-500/30" },
  news_trigger:        { label: "News Event",      description: "Relevant news or press mention",   colorClass: "text-violet-400 bg-violet-500/10 border-violet-500/30" },
  job_change_trigger:  { label: "Job Change",      description: "Lead changed roles or companies",  colorClass: "text-orange-400 bg-orange-500/10 border-orange-500/30" },
};

const SIGNAL_TYPES: Array<{ value: string; label: string }> = [
  { value: "all",                  label: "All Signals" },
  { value: "funding_trigger",      label: "Funding" },
  { value: "job_posting_trigger",  label: "Hiring" },
  { value: "news_trigger",         label: "News" },
  { value: "job_change_trigger",   label: "Job Changes" },
];

function scoreColorClass(s: number) {
  return s >= 0.7 ? "text-emerald-400" : s >= 0.4 ? "text-orange-400" : "text-red-400";
}

export default function Signals() {
  const [typeFilter, setTypeFilter] = useState("all");
  // Track which lead IDs have had outreach triggered this session
  const [triggered, setTriggered] = useState<Set<string>>(new Set());

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["signal-feed", typeFilter],
    queryFn: () =>
      signalApi.feed({
        limit: 100,
        signal_type: typeFilter === "all" ? undefined : typeFilter,
      }),
    staleTime: 30_000,
  });

  const { mutate: triggerOutreach, isPending: outreachPending, variables: outreachVars } = useMutation({
    mutationFn: (payload: { leadId: string; leadName: string }) =>
      outreachApi.sendNow(payload.leadId),
    onSuccess: (_, { leadId, leadName }) => {
      setTriggered((prev) => new Set(prev).add(leadId));
      toast.success(`Outreach triggered for ${leadName}`, {
        description: "Sequence queued — email will send within minutes",
        duration: 5000,
      });
    },
    onError: (_, { leadName }) => {
      toast.error(`Failed to trigger outreach for ${leadName}`);
    },
  });

  const signals = data?.signals ?? [];

  const typeCounts = signals.reduce<Record<string, number>>((acc, s) => {
    acc[s.signal_type] = (acc[s.signal_type] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="flex flex-col h-full">
      <Header
        title="Signal Feed"
        subtitle="Real-time buying signal triggers across all leads"
        actions={
          <Button
            size="sm"
            variant="outline"
            onClick={() => refetch()}
            disabled={isFetching}
            className="gap-2"
          >
            <RefreshCw className={cn("w-3.5 h-3.5", isFetching && "animate-spin")} />
            Refresh
          </Button>
        }
      />

      <div className="flex-1 overflow-y-auto p-6 space-y-6">

        {/* ── Summary Cards ── */}
        <div className="grid grid-cols-4 gap-3">
          {(Object.entries(SIGNAL_META) as [TriggerSignalType, typeof SIGNAL_META[TriggerSignalType]][]).map(([type, meta]) => (
            <Card
              key={type}
              className={cn(
                "p-4 cursor-pointer border transition-all hover:shadow-md",
                typeFilter === type ? "ring-2 ring-primary/60" : "",
              )}
              onClick={() => setTypeFilter(typeFilter === type ? "all" : type)}
            >
              <p className={cn("text-2xl font-bold font-mono", meta.colorClass.split(" ")[0])}>
                {typeCounts[type] ?? 0}
              </p>
              <p className="text-xs font-medium mt-0.5">{meta.label}</p>
              <p className="text-[10px] text-muted-foreground mt-0.5">{meta.description}</p>
            </Card>
          ))}
        </div>

        {/* ── Filter ── */}
        <div className="flex items-center justify-between">
          <p className="text-sm text-muted-foreground">
            {data?.count ?? 0} signals{typeFilter !== "all" ? ` · filtered by ${SIGNAL_TYPES.find((t) => t.value === typeFilter)?.label}` : ""}
          </p>
          <Select value={typeFilter} onValueChange={setTypeFilter}>
            <SelectTrigger className="w-44 text-xs h-8">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SIGNAL_TYPES.map((t) => (
                <SelectItem key={t.value} value={t.value} className="text-xs">{t.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* ── Signal List ── */}
        {isLoading ? (
          <div className="space-y-3">
            {[...Array(6)].map((_, i) => <div key={i} className="skeleton h-20 rounded-lg" />)}
          </div>
        ) : signals.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <Radio className="w-12 h-12 text-muted-foreground/20 mb-3" />
            <p className="text-sm font-medium text-muted-foreground">No signals detected yet</p>
            <p className="text-xs text-muted-foreground/60 mt-1">
              Trigger monitors run every 6 hours. New signals appear here automatically.
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {signals.map((s) => {
              const meta = SIGNAL_META[s.signal_type] ?? {
                label: s.signal_type,
                description: "",
                colorClass: "text-muted-foreground bg-secondary/30 border-border",
              };
              const alreadyTriggered = triggered.has(s.lead_id);
              const isThisPending = outreachPending && outreachVars?.leadId === s.lead_id;

              return (
                <div
                  key={s.id}
                  className="rounded-xl border border-border bg-card p-4 flex items-start gap-4 hover:bg-secondary/30 transition-colors group"
                >
                  {/* Signal type badge */}
                  <div className={cn("mt-0.5 px-2 py-1 rounded-full border text-[10px] font-semibold uppercase tracking-wide shrink-0 whitespace-nowrap", meta.colorClass)}>
                    {meta.label}
                  </div>

                  {/* Lead + metadata */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium truncate">{s.lead_name}</p>
                      <span className="text-muted-foreground text-xs">·</span>
                      <span className="text-xs text-muted-foreground flex items-center gap-1 truncate">
                        <Building2 className="w-3 h-3 shrink-0" />
                        {s.company}
                      </span>
                    </div>
                    {s.signal_metadata && Object.keys(s.signal_metadata).length > 0 && (
                      <div className="flex flex-wrap gap-x-4 gap-y-0.5 mt-1">
                        {Object.entries(s.signal_metadata).slice(0, 4).map(([k, v]) => (
                          <span key={k} className="text-[11px] text-muted-foreground">
                            <span className="capitalize">{k.replace(/_/g, " ")}: </span>
                            <span className="text-foreground/70">{String(v)}</span>
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Score + date + CTA */}
                  <div className="shrink-0 flex flex-col items-end gap-2">
                    <div className="text-right">
                      <p className={cn("text-sm font-mono font-bold", scoreColorClass(s.score))}>
                        +{Math.round(s.score * 100)}%
                      </p>
                      <p className="text-[10px] text-muted-foreground">
                        {new Date(s.triggered_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                      </p>
                    </div>

                    {alreadyTriggered ? (
                      <div className="flex items-center gap-1 text-[11px] text-emerald-400 font-medium">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        Outreach sent
                      </div>
                    ) : (
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 px-2.5 text-[11px] gap-1.5 border-violet-500/40 text-violet-400 hover:bg-violet-500/10 hover:text-violet-300 opacity-0 group-hover:opacity-100 transition-opacity"
                        loading={isThisPending}
                        onClick={() => triggerOutreach({ leadId: s.lead_id, leadName: s.lead_name })}
                      >
                        <Send className="w-3 h-3" />
                        Reach out
                      </Button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
