import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import { FlaskConical, Trophy, RefreshCw, TrendingUp, Mail, Eye, MessageSquare } from "lucide-react";
import { abTestApi, optimizationApi } from "../lib/api";
import { Header } from "../components/layout/Header";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { cn } from "../lib/utils";

const COLORS = {
  A: "#a78bfa",
  B: "#34d399",
  bar: ["#a78bfa", "#34d399", "#f87171", "#fbbf24"],
};

function formatPct(n: number) {
  return `${(n * 100).toFixed(1)}%`;
}

function MetricBar({ label, a, b }: { label: string; a: number; b: number }) {
  const max = Math.max(a, b, 0.001);
  return (
    <div className="space-y-1.5">
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className="flex items-center gap-2">
        <span className="text-xs w-8 text-right text-violet-400 font-mono">{formatPct(a)}</span>
        <div className="flex-1 flex gap-0.5 h-4">
          <div
            className="rounded-l bg-violet-500/60 transition-all"
            style={{ width: `${(a / max) * 50}%` }}
          />
          <div
            className="rounded-r bg-emerald-500/60 transition-all"
            style={{ width: `${(b / max) * 50}%` }}
          />
        </div>
        <span className="text-xs w-8 text-emerald-400 font-mono">{formatPct(b)}</span>
      </div>
    </div>
  );
}

export default function ABTests() {
  const qc = useQueryClient();

  const { data: results, isLoading } = useQuery({
    queryKey: ["ab-test-results"],
    queryFn: abTestApi.results,
    refetchInterval: 30_000,
  });

  const { data: history } = useQuery({
    queryKey: ["optimization-history"],
    queryFn: () => optimizationApi.history(5),
  });

  const { data: weights } = useQuery({
    queryKey: ["optimization-weights"],
    queryFn: optimizationApi.currentWeights,
  });

  const promote = useMutation({
    mutationFn: (sequenceId: string) => abTestApi.promoteWinner(sequenceId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ab-test-results"] }),
  });

  const runOpt = useMutation({
    mutationFn: optimizationApi.runNow,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["optimization-history"] });
      qc.invalidateQueries({ queryKey: ["optimization-weights"] });
    },
  });

  const variantA = results?.variants.find((v) => v.variant === "A");
  const variantB = results?.variants.find((v) => v.variant === "B");

  const chartData = results?.variants.map((v) => ({
    variant: `Variant ${v.variant}`,
    "Open rate": +(v.open_rate * 100).toFixed(1),
    "Reply rate": +(v.reply_rate * 100).toFixed(1),
    "Conversion rate": +(v.conversion_rate * 100).toFixed(1),
  })) ?? [];

  const weightsData = weights
    ? Object.entries(weights).map(([k, v]) => ({
        name: k.replace(/_/g, " "),
        value: +(v * 100).toFixed(1),
      }))
    : [];

  return (
    <div className="flex flex-col min-h-screen">
      <Header
        title="A/B Tests & Optimization"
        subtitle="Email sequence experiments and self-optimization loop"
      />

      <div className="flex-1 p-8 space-y-6 animate-fade-in">
        {isLoading ? (
          <div className="space-y-4">
            {[...Array(3)].map((_, i) => <div key={i} className="skeleton h-32 rounded-xl" />)}
          </div>
        ) : !results || results.variants.length === 0 ? (
          <Card>
            <CardContent className="p-12 text-center">
              <FlaskConical className="w-10 h-10 mx-auto mb-3 text-muted-foreground/30" />
              <p className="text-sm text-muted-foreground">
                No A/B test data yet. Process some leads to start collecting outreach data.
              </p>
            </CardContent>
          </Card>
        ) : (
          <>
            {/* Significance banner */}
            {results.significant && results.winner && (
              <div className="flex items-center gap-3 px-5 py-3.5 rounded-xl border border-emerald-500/30 bg-emerald-500/10 text-emerald-400">
                <Trophy className="w-5 h-5 shrink-0" />
                <div className="flex-1">
                  <span className="font-semibold">Statistically significant winner:</span>{" "}
                  Variant {results.winner}
                  {results.p_value != null && (
                    <span className="text-emerald-400/70 ml-2 text-sm">
                      (p={results.p_value.toFixed(3)})
                    </span>
                  )}
                </div>
                {results.variants.find((v) => v.variant === results.winner) && (
                  <button
                    onClick={() => {
                      const winner = results.variants.find((v) => v.variant === results.winner);
                      if (winner) promote.mutate(winner.sequence_id);
                    }}
                    disabled={promote.isPending}
                    className="px-3 py-1.5 text-xs font-medium rounded-lg bg-emerald-500 text-white hover:bg-emerald-400 transition-colors disabled:opacity-50"
                  >
                    {promote.isPending ? "Promoting…" : "Promote winner"}
                  </button>
                )}
              </div>
            )}

            {/* Variant cards */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {[variantA, variantB].filter(Boolean).map((v) => (
                <Card
                  key={v!.variant}
                  className={cn(
                    "relative overflow-hidden border",
                    results.winner === v!.variant ? "border-emerald-500/40" : "border-border"
                  )}
                >
                  {results.winner === v!.variant && (
                    <div className="absolute top-3 right-3">
                      <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30 text-xs">
                        <Trophy className="w-2.5 h-2.5 mr-1" />
                        Winner
                      </Badge>
                    </div>
                  )}
                  <CardHeader className="pb-2">
                    <div className="flex items-center gap-2">
                      <div
                        className="w-3 h-3 rounded-full"
                        style={{ background: COLORS[v!.variant as "A" | "B"] ?? "#888" }}
                      />
                      <CardTitle className="text-sm">Variant {v!.variant}</CardTitle>
                    </div>
                    <CardDescription className="truncate">{v!.sequence_name}</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="grid grid-cols-3 gap-2">
                      {[
                        { label: "Sent", value: v!.emails_sent, icon: Mail, color: "text-muted-foreground" },
                        { label: "Opened", value: v!.opens, icon: Eye, color: "text-violet-400" },
                        { label: "Replied", value: v!.replies, icon: MessageSquare, color: "text-emerald-400" },
                      ].map(({ label, value, icon: Icon, color }) => (
                        <div key={label} className="rounded-lg bg-secondary/40 p-2.5 text-center">
                          <Icon className={cn("w-3.5 h-3.5 mx-auto mb-1", color)} />
                          <p className="text-lg font-bold">{value}</p>
                          <p className="text-[10px] text-muted-foreground">{label}</p>
                        </div>
                      ))}
                    </div>
                    <div className="space-y-1.5">
                      {[
                        { label: "Open rate", value: v!.open_rate },
                        { label: "Reply rate", value: v!.reply_rate },
                        { label: "Conversion", value: v!.conversion_rate },
                      ].map(({ label, value }) => (
                        <div key={label} className="flex justify-between items-center text-xs">
                          <span className="text-muted-foreground">{label}</span>
                          <span className="font-semibold">{formatPct(value)}</span>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>

            {/* Side-by-side metric comparison */}
            {variantA && variantB && (
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">Head-to-Head Comparison</CardTitle>
                  <CardDescription>
                    Sample size: {results.sample_size} · {results.significant ? "Significant" : "Not yet significant — need more data"}
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex items-center gap-4 text-xs">
                    <div className="flex items-center gap-1.5"><div className="w-2.5 h-2.5 rounded-full bg-violet-500" /><span>Variant A</span></div>
                    <div className="flex items-center gap-1.5"><div className="w-2.5 h-2.5 rounded-full bg-emerald-500" /><span>Variant B</span></div>
                  </div>
                  <MetricBar label="Open rate" a={variantA.open_rate} b={variantB.open_rate} />
                  <MetricBar label="Reply rate" a={variantA.reply_rate} b={variantB.reply_rate} />
                  <MetricBar label="Conversion rate" a={variantA.conversion_rate} b={variantB.conversion_rate} />

                  <ResponsiveContainer width="100%" height={180}>
                    <BarChart data={chartData} barSize={32}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(217 33% 16%)" vertical={false} />
                      <XAxis dataKey="variant" tick={{ fill: "hsl(215 20% 55%)", fontSize: 11 }} axisLine={false} tickLine={false} />
                      <YAxis unit="%" tick={{ fill: "hsl(215 20% 55%)", fontSize: 11 }} axisLine={false} tickLine={false} />
                      <Tooltip
                        contentStyle={{ background: "hsl(222 47% 9%)", border: "1px solid hsl(217 33% 16%)", borderRadius: 8 }}
                      />
                      <Legend wrapperStyle={{ fontSize: "11px" }} />
                      <Bar dataKey="Open rate" fill={COLORS.bar[0]} radius={[4, 4, 0, 0]} />
                      <Bar dataKey="Reply rate" fill={COLORS.bar[1]} radius={[4, 4, 0, 0]} />
                      <Bar dataKey="Conversion rate" fill={COLORS.bar[2]} radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
            )}
          </>
        )}

        {/* BANT weight optimization */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-sm flex items-center gap-2">
                    <TrendingUp className="w-4 h-4 text-violet-400" />
                    BANT Weights (Live)
                  </CardTitle>
                  <CardDescription>Self-optimized from conversion outcomes</CardDescription>
                </div>
                <button
                  onClick={() => runOpt.mutate()}
                  disabled={runOpt.isPending}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border border-border hover:bg-secondary transition-colors disabled:opacity-50"
                >
                  <RefreshCw className={cn("w-3 h-3", runOpt.isPending && "animate-spin")} />
                  {runOpt.isPending ? "Running…" : "Run now"}
                </button>
              </div>
            </CardHeader>
            <CardContent>
              {weightsData.length > 0 ? (
                <div className="space-y-2.5">
                  {weightsData.map(({ name, value }) => (
                    <div key={name} className="space-y-1">
                      <div className="flex justify-between text-xs">
                        <span className="text-muted-foreground capitalize">{name}</span>
                        <span className="font-mono font-medium">{value.toFixed(1)}%</span>
                      </div>
                      <div className="w-full bg-secondary rounded-full h-1.5 overflow-hidden">
                        <div
                          className="h-full rounded-full bg-gradient-to-r from-violet-500 to-indigo-500 transition-all duration-500"
                          style={{ width: `${Math.min(value, 100)}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="h-24 flex items-center justify-center text-sm text-muted-foreground">
                  No optimization runs yet
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Optimization History</CardTitle>
              <CardDescription>Last {history?.runs.length ?? 0} runs</CardDescription>
            </CardHeader>
            <CardContent className="p-0 max-h-72 overflow-y-auto">
              {history?.runs.length ? (
                <div className="divide-y divide-border">
                  {history.runs.map((run) => (
                    <div key={run.id} className="px-4 py-3">
                      <div className="flex justify-between items-start">
                        <div>
                          <p className="text-xs font-medium">{new Date(run.created_at).toLocaleString()}</p>
                          <p className="text-[10px] text-muted-foreground mt-0.5">
                            {run.leads_analysed} leads analysed
                          </p>
                        </div>
                        {run.weight_delta && (
                          <div className="flex gap-2">
                            {Object.entries(run.weight_delta)
                              .filter(([, d]) => Math.abs(d) > 0.001)
                              .slice(0, 3)
                              .map(([k, d]) => (
                                <span
                                  key={k}
                                  className={cn(
                                    "text-[10px] font-mono px-1.5 py-0.5 rounded",
                                    d > 0 ? "text-emerald-400 bg-emerald-500/10" : "text-red-400 bg-red-500/10"
                                  )}
                                >
                                  {k.slice(0, 1).toUpperCase()}: {d > 0 ? "+" : ""}{(d * 100).toFixed(1)}%
                                </span>
                              ))}
                          </div>
                        )}
                      </div>
                      {run.notes && (
                        <p className="text-[10px] text-muted-foreground mt-1 italic">{run.notes}</p>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-6 text-center text-sm text-muted-foreground">
                  No optimization runs yet — click "Run now" to start.
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
