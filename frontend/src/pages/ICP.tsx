import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Save, CheckCircle2, XCircle, Users2,
  Building2, TrendingUp, RefreshCw, Info,
} from "lucide-react";
import { icpApi } from "../lib/api";
import { Header } from "../components/layout/Header";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { cn } from "../lib/utils";

// ── Static option lists ───────────────────────────────────────────────────────

const INDUSTRY_OPTIONS = [
  "SaaS", "FinTech", "Technology", "DevTools", "PropTech",
  "Software", "E-Commerce", "HealthTech", "EdTech", "InsurTech",
  "MarTech", "LegalTech", "Logistics", "Manufacturing", "Retail",
  "Non-Profit", "Government", "Banking", "Marketing", "Media",
];

const SENIORITY_OPTIONS = [
  { value: "C-Level", description: "CEO, CTO, CFO, COO, CRO, CMO" },
  { value: "VP",      description: "VP Sales, VP Engineering, VP Revenue …" },
  { value: "Director",description: "Director of Sales, Head of Growth …" },
  { value: "Manager", description: "Sales Manager, Ops Manager …" },
  { value: "IC",      description: "Account Executive, SDR, Engineer …" },
];

const SIZE_PRESETS = [
  { label: "Seed / early",  min: 1,    max: 50   },
  { label: "SMB",           min: 50,   max: 250  },
  { label: "Mid-market",    min: 250,  max: 1000 },
  { label: "Enterprise",    min: 1000, max: null  },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function pct(n: number, total: number) {
  if (!total) return "0%";
  return `${Math.round((n / total) * 100)}%`;
}

function ToggleChip({
  label, active, onClick, danger = false,
}: { label: string; active: boolean; onClick: () => void; danger?: boolean }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "px-3 py-1.5 rounded-full text-xs font-medium border transition-all select-none",
        active && !danger
          ? "bg-violet-600/20 border-violet-500/50 text-violet-300"
          : active && danger
          ? "bg-red-600/20 border-red-500/50 text-red-400"
          : "border-border text-muted-foreground hover:border-border/80 hover:text-foreground"
      )}
    >
      {active && <span className="mr-1">{danger ? "✕" : "✓"}</span>}
      {label}
    </button>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ICP() {
  const qc = useQueryClient();

  const { data: cfg, isLoading } = useQuery({
    queryKey: ["icp"],
    queryFn: icpApi.get,
  });

  const { data: preview, refetch: refetchPreview, isFetching: previewFetching } = useQuery({
    queryKey: ["icp-preview"],
    queryFn: icpApi.preview,
    staleTime: 10_000,
  });

  // Draft = null means "no unsaved changes" — use cfg as source of truth.
  // When the user edits anything, we snapshot cfg into draft and mutate draft.
  // This avoids setState-in-effect entirely.
  type DraftState = {
    industries: string[];
    seniority: string[];
    excluded: string[];
    minEmp: string;
    maxEmp: string;
  };

  const [draft, setDraft] = useState<DraftState | null>(null);

  const savedState: DraftState = {
    industries: cfg?.industries ?? [],
    seniority:  cfg?.seniority_levels ?? [],
    excluded:   cfg?.excluded_industries ?? [],
    minEmp:     cfg?.min_employees != null ? String(cfg.min_employees) : "",
    maxEmp:     cfg?.max_employees != null ? String(cfg.max_employees) : "",
  };

  // Current form values = draft if present, otherwise saved state
  const form = draft ?? savedState;
  const { industries, seniority, excluded, minEmp, maxEmp } = form;
  const dirty = draft !== null;

  function patch(updates: Partial<DraftState>) {
    setDraft((prev) => ({ ...(prev ?? savedState), ...updates }));
  }

  function toggleList(field: keyof Pick<DraftState, "industries" | "seniority" | "excluded">, item: string) {
    const current = form[field];
    patch({ [field]: current.includes(item) ? current.filter((x) => x !== item) : [...current, item] });
  }

  function applyPreset(min: number, max: number | null) {
    patch({ minEmp: String(min), maxEmp: max != null ? String(max) : "" });
  }

  const { mutate: save, isPending: saving } = useMutation({
    mutationFn: () =>
      icpApi.update({
        industries,
        seniority_levels: seniority,
        excluded_industries: excluded,
        min_employees: minEmp ? parseInt(minEmp, 10) : null,
        max_employees: maxEmp ? parseInt(maxEmp, 10) : null,
      }),
    onSuccess: () => {
      toast.success("ICP saved — scoring will use updated criteria");
      setDraft(null);
      qc.invalidateQueries({ queryKey: ["icp"] });
      qc.invalidateQueries({ queryKey: ["icp-preview"] });
    },
    onError: () => toast.error("Failed to save ICP"),
  });

  const noCriteria = industries.length === 0 && seniority.length === 0 && !minEmp && !maxEmp;

  if (isLoading) {
    return (
      <div className="flex flex-col min-h-screen">
        <Header title="ICP Builder" subtitle="Define your ideal customer profile" />
        <div className="flex-1 p-8 space-y-4">
          {[...Array(3)].map((_, i) => <div key={i} className="skeleton h-40 rounded-xl" />)}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col min-h-screen">
      <Header
        title="ICP Builder"
        subtitle="Define who your ideal customer is — the pipeline scores against this automatically"
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => refetchPreview()}
              loading={previewFetching}
              className="gap-1.5"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Refresh preview
            </Button>
            <Button
              variant="gradient"
              size="sm"
              onClick={() => save()}
              loading={saving}
              disabled={!dirty || noCriteria}
              className="gap-1.5"
            >
              <Save className="w-3.5 h-3.5" />
              {dirty ? "Save ICP" : "Saved"}
            </Button>
          </div>
        }
      />

      <div className="flex-1 p-8 space-y-6 animate-fade-in">

        {/* ── Live preview banner ─────────────────────────────────────── */}
        <div className={cn(
          "rounded-xl border p-5",
          preview?.unconfigured || noCriteria
            ? "border-border bg-card"
            : "border-violet-500/20 bg-violet-500/5"
        )}>
          {preview?.unconfigured || noCriteria ? (
            <div className="flex items-center gap-3 text-muted-foreground">
              <Info className="w-4 h-4 shrink-0" />
              <p className="text-sm">
                No ICP configured yet. Set your target criteria below — the pipeline will
                evaluate new leads against them automatically.
              </p>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-6">
              <div>
                <p className="text-xs text-muted-foreground">Leads matching ICP</p>
                <p className="text-3xl font-bold text-violet-400">
                  {preview?.matched ?? 0}
                  <span className="text-lg text-muted-foreground font-normal ml-1">
                    / {preview?.total ?? 0}
                  </span>
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {pct(preview?.matched ?? 0, preview?.total ?? 0)} of pipeline
                </p>
              </div>
              <div className="flex gap-4">
                {(["hot", "warm", "cold"] as const).map((v) => (
                  <div key={v} className="text-center">
                    <p className={cn("text-xl font-bold",
                      v === "hot" ? "text-red-400" : v === "warm" ? "text-orange-400" : "text-blue-400"
                    )}>
                      {preview?.[v] ?? 0}
                    </p>
                    <p className="text-[10px] text-muted-foreground capitalize">{v}</p>
                  </div>
                ))}
              </div>
              {dirty && (
                <Badge variant="secondary" className="text-xs ml-auto">
                  Unsaved changes — save to apply
                </Badge>
              )}
            </div>
          )}
        </div>

        {/* ── Grid of criteria cards ──────────────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

          {/* Target industries */}
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center gap-2">
                <Building2 className="w-4 h-4 text-violet-400" />
                <CardTitle className="text-sm">Target Industries</CardTitle>
              </div>
              <CardDescription>
                Leads in these industries score as ICP match.
                {industries.length > 0 && (
                  <span className="ml-1 font-medium text-violet-400">{industries.length} selected</span>
                )}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2">
                {INDUSTRY_OPTIONS.filter((i) => !excluded.includes(i)).map((ind) => (
                  <ToggleChip
                    key={ind}
                    label={ind}
                    active={industries.includes(ind)}
                    onClick={() => toggleList("industries", ind)}
                  />
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Decision-maker seniority */}
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center gap-2">
                <Users2 className="w-4 h-4 text-violet-400" />
                <CardTitle className="text-sm">Decision-maker Seniority</CardTitle>
              </div>
              <CardDescription>
                Leads at these seniority levels qualify for Authority criterion.
                {seniority.length > 0 && (
                  <span className="ml-1 font-medium text-violet-400">{seniority.length} selected</span>
                )}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {SENIORITY_OPTIONS.map(({ value, description }) => (
                  <button
                    key={value}
                    onClick={() => toggleList("seniority", value)}
                    className={cn(
                      "w-full flex items-center gap-3 rounded-lg px-4 py-3 border transition-all text-left",
                      seniority.includes(value)
                        ? "border-violet-500/40 bg-violet-500/10"
                        : "border-border hover:border-border/80 hover:bg-secondary/30"
                    )}
                  >
                    <div className={cn(
                      "w-4 h-4 rounded border flex items-center justify-center shrink-0",
                      seniority.includes(value)
                        ? "border-violet-500 bg-violet-500"
                        : "border-border"
                    )}>
                      {seniority.includes(value) && (
                        <CheckCircle2 className="w-3 h-3 text-white" />
                      )}
                    </div>
                    <div>
                      <p className="text-sm font-medium">{value}</p>
                      <p className="text-xs text-muted-foreground">{description}</p>
                    </div>
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Company size */}
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-violet-400" />
                <CardTitle className="text-sm">Company Size Range</CardTitle>
              </div>
              <CardDescription>
                Target employee count range. Leave blank to accept any size.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center gap-3">
                <div className="flex-1">
                  <label className="text-xs text-muted-foreground mb-1 block">Min employees</label>
                  <input
                    type="number"
                    min="0"
                    value={minEmp}
                    onChange={(e) => patch({ minEmp: e.target.value })}
                    placeholder="e.g. 50"
                    className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
                  />
                </div>
                <span className="text-muted-foreground mt-5">–</span>
                <div className="flex-1">
                  <label className="text-xs text-muted-foreground mb-1 block">Max employees</label>
                  <input
                    type="number"
                    min="0"
                    value={maxEmp}
                    onChange={(e) => patch({ maxEmp: e.target.value })}
                    placeholder="e.g. 1000"
                    className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
                  />
                </div>
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-2">Quick presets</p>
                <div className="flex flex-wrap gap-2">
                  {SIZE_PRESETS.map(({ label, min, max }) => {
                    const active =
                      String(min) === minEmp &&
                      (max == null ? maxEmp === "" : String(max) === maxEmp);
                    return (
                      <button
                        key={label}
                        onClick={() => applyPreset(min, max)}
                        className={cn(
                          "px-3 py-1 rounded-full text-xs border transition-all",
                          active
                            ? "border-violet-500/50 bg-violet-500/10 text-violet-300"
                            : "border-border text-muted-foreground hover:text-foreground"
                        )}
                      >
                        {label}
                        <span className="ml-1 opacity-60">
                          ({min}{max ? `–${max}` : "+"})
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Excluded industries */}
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center gap-2">
                <XCircle className="w-4 h-4 text-red-400" />
                <CardTitle className="text-sm">Excluded Industries</CardTitle>
              </div>
              <CardDescription>
                Leads in these industries are always marked as ICP mismatch, regardless of other scores.
                {excluded.length > 0 && (
                  <span className="ml-1 font-medium text-red-400">{excluded.length} excluded</span>
                )}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2">
                {INDUSTRY_OPTIONS.filter((i) => !industries.includes(i)).map((ind) => (
                  <ToggleChip
                    key={ind}
                    label={ind}
                    active={excluded.includes(ind)}
                    danger
                    onClick={() => toggleList("excluded", ind)}
                  />
                ))}
              </div>
              {excluded.length === 0 && (
                <p className="text-xs text-muted-foreground mt-2">
                  No industries excluded — select any above to always disqualify them.
                </p>
              )}
            </CardContent>
          </Card>
        </div>

        {/* ── Metadata footer ─────────────────────────────────────────── */}
        {cfg?.updated_at && (
          <p className="text-xs text-muted-foreground text-center">
            Last updated {new Date(cfg.updated_at).toLocaleString()} by {cfg.updated_by_id ? "a manager" : "unknown"}
          </p>
        )}
      </div>
    </div>
  );
}
