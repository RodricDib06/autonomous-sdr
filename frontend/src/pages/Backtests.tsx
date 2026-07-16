import { useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import {
  ArrowUpFromLine, History, Crosshair, Gauge, TrendingUp, Percent, AlertTriangle, FileText,
} from "lucide-react";
import { toast } from "sonner";
import { backtestsApi, type BacktestRun, type BacktestSummary } from "../lib/api";
import { Header } from "../components/layout/Header";
import { StatCard } from "../components/StatCard";
import { VerdictBadge } from "../components/VerdictBadge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { cn, formatDate, apiErrorMessage } from "../lib/utils";

// Two-series palette validated for CVD + contrast on the app's dark surface
const SERIES_COLORS = { predicted: "#8b5cf6", actual: "#059669" };

const pct = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 100)}%`);

// ── Upload ────────────────────────────────────────────────────────────────────

function UploadZone({ onFile, uploading }: { onFile: (f: File) => void; uploading: boolean }) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const takeFile = (file: File | undefined) => {
    if (!file) return;
    if (!file.name.endsWith(".csv")) { toast.error("Only CSV files are supported"); return; }
    onFile(file);
  };

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); takeFile(e.dataTransfer.files[0]); }}
      onClick={() => inputRef.current?.click()}
      className={cn(
        "border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all",
        dragging ? "border-primary bg-primary/10" : "border-border hover:border-primary/50 hover:bg-secondary/30",
        uploading && "opacity-60 pointer-events-none"
      )}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".csv"
        className="hidden"
        aria-label="Backtest CSV file"
        onChange={(e) => { takeFile(e.target.files?.[0]); e.target.value = ""; }}
      />
      <div className="flex flex-col items-center gap-3">
        <div className={cn("w-12 h-12 rounded-xl flex items-center justify-center", dragging ? "bg-primary/20" : "bg-secondary")}>
          <ArrowUpFromLine className={cn("w-6 h-6", dragging ? "text-primary" : "text-muted-foreground")} />
        </div>
        <div>
          <p className="font-semibold text-sm">{uploading ? "Scoring…" : "Drop last quarter's CRM export"}</p>
          <p className="text-xs text-muted-foreground mt-0.5">or click to browse · every row is re-qualified and compared to how it really closed</p>
        </div>
        <div className="flex flex-wrap justify-center gap-1.5">
          {["name", "email", "company", "outcome"].map((f) => (
            <Badge key={f} variant="secondary" className="font-mono text-[10px]">{f}</Badge>
          ))}
          {["job_title", "seniority", "industry", "company_size"].map((f) => (
            <Badge key={f} variant="outline" className="font-mono text-[10px] text-muted-foreground">{f}?</Badge>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Report pieces ─────────────────────────────────────────────────────────────

function MatrixCard({ summary }: { summary: BacktestSummary }) {
  const rows = (["Hot", "Warm", "Cold"] as const).map((verdict) => {
    const cell = summary.verdict_outcome_matrix[verdict];
    const total = cell.won + cell.lost;
    return { verdict, ...cell, total, winRate: total > 0 ? cell.won / total : null };
  });

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Verdict vs. reality</CardTitle>
        <CardDescription>What the agent said, next to what actually happened</CardDescription>
      </CardHeader>
      <CardContent>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-muted-foreground border-b border-border">
              <th className="text-left font-medium py-2">Agent verdict</th>
              <th className="text-right font-medium py-2">Won</th>
              <th className="text-right font-medium py-2">Lost</th>
              <th className="text-right font-medium py-2">Win rate</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.verdict} className="border-b border-border/60 last:border-0">
                <td className="py-2"><VerdictBadge verdict={row.verdict} /></td>
                <td className="text-right py-2 font-semibold text-emerald-400">{row.won}</td>
                <td className="text-right py-2 text-muted-foreground">{row.lost}</td>
                <td className="text-right py-2 font-semibold">{pct(row.winRate)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="text-muted-foreground">
              <td className="py-2">All leads</td>
              <td className="text-right py-2">{summary.won}</td>
              <td className="text-right py-2">{summary.lost}</td>
              <td className="text-right py-2">{pct(summary.base_win_rate)}</td>
            </tr>
          </tfoot>
        </table>
      </CardContent>
    </Card>
  );
}

function CalibrationCard({ summary }: { summary: BacktestSummary }) {
  const data = summary.calibration.map((bucket) => ({
    bucket: `${Math.round(bucket.range[0] * 100)}–${Math.round(bucket.range[1] * 100)}`,
    leads: bucket.count,
    "Predicted score": bucket.mean_predicted_score != null ? Math.round(bucket.mean_predicted_score * 100) : null,
    "Actual win rate": bucket.actual_win_rate != null ? Math.round(bucket.actual_win_rate * 100) : null,
  }));

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Calibration</CardTitle>
        <CardDescription>Per score bucket: what the model predicted vs. the real win rate — matched bars mean an honest model</CardDescription>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={data} barSize={18} barGap={2}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(217 33% 16%)" vertical={false} />
            <XAxis dataKey="bucket" tick={{ fill: "hsl(215 20% 55%)", fontSize: 11 }} axisLine={false} tickLine={false} />
            <YAxis unit="%" domain={[0, 100]} tick={{ fill: "hsl(215 20% 55%)", fontSize: 11 }} axisLine={false} tickLine={false} />
            <Tooltip
              cursor={{ fill: "hsl(217 33% 17% / 0.4)" }}
              contentStyle={{ background: "hsl(222 47% 9%)", border: "1px solid hsl(217 33% 16%)", borderRadius: 8, fontSize: 12 }}
              formatter={(value, name) => [`${value ?? "—"}%`, String(name ?? "")]}
              labelFormatter={(label) => {
                const bucket = data.find((d) => d.bucket === label);
                return `Score ${String(label)} · ${bucket?.leads ?? 0} lead(s)`;
              }}
            />
            <Legend wrapperStyle={{ fontSize: "11px" }} />
            <Bar dataKey="Predicted score" fill={SERIES_COLORS.predicted} radius={[4, 4, 0, 0]} />
            <Bar dataKey="Actual win rate" fill={SERIES_COLORS.actual} radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}

function RecordsCard({ runId }: { runId: string }) {
  const [missesOnly, setMissesOnly] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["backtest-records", runId, missesOnly],
    queryFn: () => backtestsApi.records(runId, { misses_only: missesOnly || undefined, limit: 100 }),
  });

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-sm">Row-by-row</CardTitle>
            <CardDescription>
              {missesOnly ? "Where the agent and reality disagreed" : "Every scored lead"}
              {data ? ` · ${data.total} row(s)` : ""}
            </CardDescription>
          </div>
          <Button
            size="sm"
            variant={missesOnly ? "gradient" : "outline"}
            onClick={() => setMissesOnly(!missesOnly)}
            className="gap-1.5"
            aria-pressed={missesOnly}
          >
            <Crosshair className="w-3.5 h-3.5" />
            Misses only
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-sm text-muted-foreground py-6 text-center">Loading…</p>
        ) : (data?.records.length ?? 0) === 0 ? (
          <p className="text-sm text-muted-foreground py-6 text-center">
            {missesOnly ? "No misses — every Hot won or Cold lost in this set" : "No records"}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-muted-foreground border-b border-border">
                  <th className="text-left font-medium py-2 pr-3">Lead</th>
                  <th className="text-left font-medium py-2 pr-3">Predicted</th>
                  <th className="text-right font-medium py-2 pr-3">Score</th>
                  <th className="text-left font-medium py-2 pr-3">Actual</th>
                  <th className="text-left font-medium py-2">Notes</th>
                </tr>
              </thead>
              <tbody>
                {data!.records.map((rec) => (
                  <tr key={rec.row_number} className="border-b border-border/60 last:border-0">
                    <td className="py-2 pr-3">
                      <p className="font-medium truncate max-w-[180px]">{rec.name}</p>
                      <p className="text-muted-foreground truncate max-w-[180px]">{rec.company}</p>
                    </td>
                    <td className="py-2 pr-3"><VerdictBadge verdict={rec.predicted_verdict} /></td>
                    <td className="py-2 pr-3 text-right font-mono">{Math.round(rec.predicted_score * 100)}</td>
                    <td className="py-2 pr-3">
                      <Badge variant={rec.actual_outcome === "won" ? "success" : "secondary"} className="text-[10px]">
                        {rec.actual_outcome}
                      </Badge>
                    </td>
                    <td className="py-2 text-muted-foreground">
                      {rec.features?.defaulted?.length
                        ? `defaulted: ${rec.features.defaulted.join(", ")}`
                        : rec.features?.guardrail_flag ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data!.total > data!.records.length && (
              <p className="text-[11px] text-muted-foreground mt-2">
                Showing first {data!.records.length} of {data!.total}
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function RunReport({ runId }: { runId: string }) {
  const { data: run, isLoading } = useQuery({
    queryKey: ["backtest", runId],
    queryFn: () => backtestsApi.get(runId),
  });

  if (isLoading) return <p className="text-sm text-muted-foreground py-8 text-center">Loading report…</p>;
  if (!run?.summary) return null;
  const s = run.summary;

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="Hot recall"
          value={pct(s.hot_recall)}
          sub="of your closed-won deals were flagged Hot"
          icon={Crosshair}
          accent="violet"
        />
        <StatCard
          title="Hot precision"
          value={pct(s.hot_precision)}
          sub="of Hot verdicts actually closed"
          icon={Gauge}
          accent="emerald"
        />
        <StatCard
          title="Hot lift"
          value={s.hot_lift != null ? `${s.hot_lift}×` : "—"}
          sub="win rate in Hot vs. your base rate"
          icon={TrendingUp}
          accent="orange"
        />
        <StatCard
          title="Base win rate"
          value={pct(s.base_win_rate)}
          sub={`${s.won} won / ${s.lost} lost of ${s.total}`}
          icon={Percent}
          accent="blue"
        />
      </div>

      {run.errors && (
        <div className="flex items-start gap-2 text-xs text-yellow-400 bg-yellow-500/10 border border-yellow-500/20 rounded-lg px-3 py-2">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">{run.skipped_rows} row(s) skipped</p>
            <pre className="whitespace-pre-wrap font-sans text-yellow-400/80 mt-0.5 max-h-24 overflow-y-auto">{run.errors}</pre>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <MatrixCard summary={s} />
        <CalibrationCard summary={s} />
      </div>

      <RecordsCard runId={runId} />
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Backtests() {
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data: runsData, isLoading } = useQuery({
    queryKey: ["backtests"],
    queryFn: backtestsApi.list,
  });

  const { mutate: upload, isPending: uploading } = useMutation({
    mutationFn: backtestsApi.upload,
    onSuccess: (run: BacktestRun) => {
      qc.invalidateQueries({ queryKey: ["backtests"] });
      qc.setQueryData(["backtest", run.id], run);
      setSelectedId(run.id);
      toast.success(`Scored ${run.total_rows} leads from ${run.filename}`);
    },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, "Backtest failed — check the CSV columns")),
  });

  const runs = runsData?.runs ?? [];
  const activeId = selectedId ?? runs[0]?.id ?? null;

  return (
    <div className="flex flex-col min-h-screen">
      <Header
        title="Backtests"
        subtitle="Replay a historical CRM export through the qualifier — argue with your own data, not ours"
      />
      <div className="flex-1 p-8 space-y-6 max-w-6xl animate-fade-in">
        <UploadZone onFile={(f) => upload(f)} uploading={uploading} />

        {isLoading ? (
          <p className="text-sm text-muted-foreground py-8 text-center">Loading…</p>
        ) : runs.length === 0 ? (
          <Card>
            <CardContent className="py-12 text-center">
              <History className="w-8 h-8 text-muted-foreground mx-auto mb-3" />
              <p className="text-sm font-medium">No backtests yet</p>
              <p className="text-xs text-muted-foreground mt-1 max-w-md mx-auto">
                Export last quarter's closed deals from your CRM with a won/lost column.
                The agent re-qualifies every lead and shows how its verdicts line up with what actually closed.
              </p>
            </CardContent>
          </Card>
        ) : (
          <>
            <div className="flex flex-wrap gap-2" role="tablist" aria-label="Backtest runs">
              {runs.map((run) => (
                <button
                  key={run.id}
                  role="tab"
                  aria-selected={run.id === activeId}
                  onClick={() => setSelectedId(run.id)}
                  className={cn(
                    "flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs transition-colors",
                    run.id === activeId
                      ? "border-violet-500 bg-violet-500/10 text-foreground"
                      : "border-border text-muted-foreground hover:bg-secondary/40"
                  )}
                >
                  <FileText className="w-3 h-3 shrink-0" />
                  <span className="font-medium max-w-[160px] truncate">{run.filename}</span>
                  <span>{run.total_rows} rows · {formatDate(run.created_at)}</span>
                </button>
              ))}
            </div>

            {activeId && <RunReport runId={activeId} />}
          </>
        )}
      </div>
    </div>
  );
}
