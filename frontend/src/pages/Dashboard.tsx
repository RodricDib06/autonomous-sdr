import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell,
} from "recharts";
import {
  Flame, Users2, CheckCircle2, Clock, AlertCircle, Zap, Mail,
  Calendar, DollarSign, Pencil, Timer, TrendingDown,
} from "lucide-react";
import { leadsApi, outreachApi, abTestApi, decayApi } from "../lib/api";
import { useGlobalEvents } from "../hooks/useGlobalEvents";
import type { GlobalEvent } from "../types";
import { Header } from "../components/layout/Header";
import { StatCard } from "../components/StatCard";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Progress } from "../components/ui/progress";
import { Input } from "../components/ui/input";
import { formatPercent, cn } from "../lib/utils";

const ACV_KEY = "asdr_acv";

function useACV() {
  const [acv, setAcvState] = useState<number>(() => {
    const stored = localStorage.getItem(ACV_KEY);
    return stored ? Number(stored) : 25000;
  });
  const setAcv = (v: number) => {
    localStorage.setItem(ACV_KEY, String(v));
    setAcvState(v);
  };
  return [acv, setAcv] as const;
}

function formatPipelineValue(v: number): string {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`;
  return `$${v.toLocaleString()}`;
}

const VERDICT_COLORS = { hot: "#f87171", warm: "#fb923c", cold: "#60a5fa" };
const QUALITY_COLORS = { excellent: "#34d399", good: "#a3e635", fair: "#fbbf24", poor: "#f87171" };

export default function Dashboard() {
  const qc = useQueryClient();
  const [acv, setAcv] = useACV();
  const [editingAcv, setEditingAcv] = useState(false);
  const [acvInput, setAcvInput] = useState("");

  // Real-time SSE notifications
  useGlobalEvents({
    onLeadComplete: (event: GlobalEvent) => {
      const { verdict, lead_name, company } = event;
      if (verdict === "Hot") {
        toast.success(`New hot lead: ${lead_name} @ ${company}`, {
          description: "Ready for outreach — view in Leads",
          duration: 6000,
        });
      } else if (verdict === "Warm") {
        toast(`Warm lead qualified: ${lead_name} @ ${company}`, {
          description: "Added to nurture queue",
          duration: 4000,
        });
      }
      // Refetch live data on any lead completion
      qc.invalidateQueries({ queryKey: ["stats"] });
      qc.invalidateQueries({ queryKey: ["hot"] });
      qc.invalidateQueries({ queryKey: ["cooling"] });
    },
    onOptimization: () => {
      toast("BANT weights updated", { description: "Self-optimization run completed", duration: 4000 });
      qc.invalidateQueries({ queryKey: ["optimization-weights"] });
    },
  });

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ["stats"],
    queryFn: leadsApi.stats,
    refetchInterval: 30_000,
  });

  const { data: hotData, isLoading: hotLoading } = useQuery({
    queryKey: ["hot"],
    queryFn: () => leadsApi.hot(10),
    refetchInterval: 30_000,
  });

  const { data: quality } = useQuery({
    queryKey: ["quality"],
    queryFn: leadsApi.qualityReport,
    refetchInterval: 60_000,
  });

  const { data: outreachStats } = useQuery({
    queryKey: ["outreach-stats"],
    queryFn: outreachApi.stats,
    refetchInterval: 60_000,
  });

  const { data: abResults } = useQuery({
    queryKey: ["ab-test-results"],
    queryFn: abTestApi.results,
    refetchInterval: 60_000,
  });

  const { data: coolingData } = useQuery({
    queryKey: ["cooling"],
    queryFn: () => decayApi.cooling(5),
    refetchInterval: 60_000,
  });

  const verdictData = stats
    ? [
        { name: "Hot", value: stats.verdict_breakdown.hot, fill: VERDICT_COLORS.hot },
        { name: "Warm", value: stats.verdict_breakdown.warm, fill: VERDICT_COLORS.warm },
        { name: "Cold", value: stats.verdict_breakdown.cold, fill: VERDICT_COLORS.cold },
      ]
    : [];

  const qualityData = quality?.quality_distribution
    ? Object.entries(quality.quality_distribution).map(([k, v]) => ({
        name: k.charAt(0).toUpperCase() + k.slice(1),
        value: v,
        fill: QUALITY_COLORS[k as keyof typeof QUALITY_COLORS],
      }))
    : [];

  return (
    <div className="flex flex-col min-h-screen">
      <Header
        title="Dashboard"
        subtitle="Real-time overview of your lead pipeline"
      />

      <div className="flex-1 p-8 space-y-8 animate-fade-in">
        {/* KPI row */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            title="Total Leads"
            value={stats?.total_leads ?? "—"}
            sub="all time"
            icon={Users2}
            accent="violet"
            loading={statsLoading}
          />
          <StatCard
            title="Completed"
            value={stats?.completed ?? "—"}
            sub={stats ? formatPercent(stats.success_rate) + " success rate" : undefined}
            icon={CheckCircle2}
            accent="emerald"
            loading={statsLoading}
          />
          <StatCard
            title="Hot Leads"
            value={stats?.verdict_breakdown.hot ?? "—"}
            sub="ready for outreach"
            icon={Flame}
            accent="red"
            loading={statsLoading}
          />
          <StatCard
            title="Processing"
            value={stats ? stats.processing + stats.failed : "—"}
            sub={stats?.failed ? `${stats.failed} failed` : "in queue"}
            icon={stats?.failed ? AlertCircle : Clock}
            accent={stats?.failed ? "orange" : "blue"}
            loading={statsLoading}
          />
        </div>

        {/* Pipeline revenue value banner */}
        <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 px-6 py-4 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-emerald-500/10 flex items-center justify-center">
              <DollarSign className="w-5 h-5 text-emerald-400" />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Estimated Pipeline Value</p>
              <p className="text-2xl font-bold text-emerald-400">
                {stats ? formatPipelineValue((stats.verdict_breakdown.hot + stats.verdict_breakdown.warm) * acv) : "—"}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span>{stats ? stats.verdict_breakdown.hot + stats.verdict_breakdown.warm : 0} qualified leads</span>
            <span>×</span>
            {editingAcv ? (
              <form
                className="flex items-center gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  const v = Number(acvInput.replace(/[^0-9]/g, ""));
                  if (v > 0) setAcv(v);
                  setEditingAcv(false);
                }}
              >
                <Input
                  autoFocus
                  className="h-7 w-28 text-xs"
                  value={acvInput}
                  onChange={(e) => setAcvInput(e.target.value)}
                  placeholder="avg deal $"
                />
                <button type="submit" className="text-emerald-400 hover:text-emerald-300 text-xs font-medium">save</button>
                <button type="button" onClick={() => setEditingAcv(false)} className="text-muted-foreground hover:text-foreground text-xs">cancel</button>
              </form>
            ) : (
              <button
                onClick={() => { setAcvInput(String(acv)); setEditingAcv(true); }}
                className="flex items-center gap-1 px-2 py-1 rounded hover:bg-secondary/50 transition-colors group"
              >
                ACV {formatPipelineValue(acv)}
                <Pencil className="w-3 h-3 opacity-0 group-hover:opacity-60 transition-opacity" />
              </button>
            )}
          </div>
        </div>

        {/* Outreach KPI row */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            title="Emails Sent"
            value={outreachStats?.total_sent ?? "—"}
            sub="all time"
            icon={Mail}
            accent="blue"
          />
          <StatCard
            title="Open Rate"
            value={outreachStats ? formatPercent(outreachStats.open_rate) : "—"}
            sub={`${outreachStats?.total_opened ?? 0} opened`}
            icon={Mail}
            accent="violet"
          />
          <StatCard
            title="Reply Rate"
            value={outreachStats ? formatPercent(outreachStats.reply_rate) : "—"}
            sub={`${outreachStats?.total_replied ?? 0} replied`}
            icon={Mail}
            accent="emerald"
          />
          <StatCard
            title="A/B Winner"
            value={abResults?.winner ? `Variant ${abResults.winner}` : "—"}
            sub={abResults?.significant ? "statistically significant" : "collecting data…"}
            icon={Calendar}
            accent={abResults?.significant ? "emerald" : "orange"}
          />
        </div>

        {/* Charts row */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Verdict breakdown */}
          <Card className="lg:col-span-1">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Verdict Breakdown</CardTitle>
              <CardDescription>Qualification distribution</CardDescription>
            </CardHeader>
            <CardContent>
              {verdictData.length > 0 ? (
                <>
                  <ResponsiveContainer width="100%" height={180}>
                    <PieChart>
                      <Pie
                        data={verdictData}
                        cx="50%"
                        cy="50%"
                        innerRadius={50}
                        outerRadius={80}
                        paddingAngle={3}
                        dataKey="value"
                      >
                        {verdictData.map((entry, index) => (
                          <Cell key={index} fill={entry.fill} stroke="transparent" />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={{ background: "hsl(222 47% 9%)", border: "1px solid hsl(217 33% 16%)", borderRadius: 8 }}
                        labelStyle={{ color: "hsl(210 40% 98%)" }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="flex justify-center gap-4 mt-2">
                    {verdictData.map((d) => (
                      <div key={d.name} className="flex items-center gap-1.5 text-xs">
                        <span className="w-2.5 h-2.5 rounded-full" style={{ background: d.fill }} />
                        <span className="text-muted-foreground">{d.name}</span>
                        <span className="font-medium">{d.value}</span>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <div className="h-[180px] flex items-center justify-center text-sm text-muted-foreground">
                  No qualified leads yet
                </div>
              )}
            </CardContent>
          </Card>

          {/* Quality distribution */}
          <Card className="lg:col-span-1">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Data Quality</CardTitle>
              <CardDescription>
                Avg score: {quality ? Math.round((quality.avg_quality_score ?? 0) * 100) : "—"}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {qualityData.length > 0 ? (
                qualityData.map((d) => (
                  <div key={d.name} className="space-y-1">
                    <div className="flex justify-between text-xs">
                      <span className="text-muted-foreground">{d.name}</span>
                      <span className="font-medium">{d.value}</span>
                    </div>
                    <Progress
                      value={quality ? (d.value / quality.total_leads) * 100 : 0}
                      indicatorClassName=""
                      className="h-1.5"
                      style={{ "--tw-bg-opacity": "1" } as React.CSSProperties}
                    >
                    </Progress>
                    <div className="w-full bg-secondary rounded-full h-1.5 overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{
                          width: quality ? `${(d.value / quality.total_leads) * 100}%` : "0%",
                          background: d.fill,
                        }}
                      />
                    </div>
                  </div>
                ))
              ) : (
                <div className="h-[160px] flex items-center justify-center text-sm text-muted-foreground">
                  No quality data yet
                </div>
              )}
            </CardContent>
          </Card>

          {/* Pipeline funnel */}
          <Card className="lg:col-span-1">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Pipeline Status</CardTitle>
              <CardDescription>Lead processing stages</CardDescription>
            </CardHeader>
            <CardContent>
              {stats ? (
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart
                    data={[
                      { name: "Total", value: stats.total_leads },
                      { name: "Done", value: stats.completed },
                      { name: "Hot", value: stats.verdict_breakdown.hot },
                      { name: "Warm", value: stats.verdict_breakdown.warm },
                    ]}
                    barSize={32}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(217 33% 16%)" vertical={false} />
                    <XAxis dataKey="name" tick={{ fill: "hsl(215 20% 55%)", fontSize: 11 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: "hsl(215 20% 55%)", fontSize: 11 }} axisLine={false} tickLine={false} />
                    <Tooltip
                      contentStyle={{ background: "hsl(222 47% 9%)", border: "1px solid hsl(217 33% 16%)", borderRadius: 8 }}
                      cursor={{ fill: "hsl(217 33% 16%)" }}
                    />
                    <Bar dataKey="value" fill="hsl(263 70% 60%)" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-[200px] flex items-center justify-center text-sm text-muted-foreground">
                  No data yet
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Cooling leads — warm leads going silent */}
        {coolingData && coolingData.count > 0 && (
          <Card className="border-orange-500/20">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Timer className="w-4 h-4 text-orange-400" />
                    Cooling Leads — At Risk of Going Cold
                  </CardTitle>
                  <CardDescription>
                    Warm leads that haven't engaged in 7+ days · respond before they go cold
                  </CardDescription>
                </div>
                <Badge variant="secondary" className="text-xs border-orange-500/30 text-orange-400">
                  {coolingData.count} at risk
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              <div className="divide-y divide-border">
                {coolingData.leads.map((lead) => {
                  const urgent = lead.decay.urgency === "urgent";
                  return (
                    <div key={lead.id} className="flex items-center gap-4 px-6 py-3.5 hover:bg-secondary/20 transition-colors">
                      <div className={cn(
                        "flex items-center justify-center w-8 h-8 rounded-full text-white text-xs font-semibold shrink-0",
                        urgent
                          ? "bg-gradient-to-br from-red-600 to-orange-600"
                          : "bg-gradient-to-br from-orange-500 to-yellow-500"
                      )}>
                        {lead.name.slice(0, 2).toUpperCase()}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">{lead.name}</p>
                        <p className="text-xs text-muted-foreground truncate">
                          {lead.job_title ?? lead.email} · {lead.company}
                        </p>
                      </div>
                      <div className="hidden md:flex items-center gap-1.5 text-xs text-muted-foreground">
                        <TrendingDown className={cn("w-3.5 h-3.5", urgent ? "text-red-400" : "text-orange-400")} />
                        <span className={urgent ? "text-red-400 font-medium" : "text-orange-400"}>
                          {lead.decay.days_since_engagement}d silent
                        </span>
                      </div>
                      <div className="w-20 shrink-0">
                        <div className="h-1.5 rounded-full bg-secondary overflow-hidden">
                          <div
                            className={cn("h-full rounded-full", urgent ? "bg-red-500" : "bg-orange-400")}
                            style={{ width: `${lead.decay.decay_score * 100}%` }}
                          />
                        </div>
                        <p className="text-[10px] text-muted-foreground text-right mt-0.5">
                          {Math.round(lead.decay.decay_score * 100)}% engaged
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Hot leads feed */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-sm flex items-center gap-2">
                  <Flame className="w-4 h-4 text-red-400" />
                  Hot Leads — Ready for Outreach
                </CardTitle>
                <CardDescription>Highest confidence scores · updated every 30s</CardDescription>
              </div>
              <Badge variant="hot" className="text-xs">{hotData?.count ?? 0} leads</Badge>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {hotLoading ? (
              <div className="p-6 space-y-3">
                {[...Array(4)].map((_, i) => (
                  <div key={i} className="skeleton h-12 rounded-lg" />
                ))}
              </div>
            ) : hotData?.hot_leads.length ? (
              <div className="divide-y divide-border">
                {hotData.hot_leads.map((lead) => (
                  <div key={lead.id} className="flex items-center gap-4 px-6 py-3.5 hover:bg-secondary/30 transition-colors">
                    <div className="flex items-center justify-center w-8 h-8 rounded-full bg-gradient-to-br from-violet-600 to-indigo-600 text-white text-xs font-semibold shrink-0">
                      {lead.name.slice(0, 2).toUpperCase()}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{lead.name}</p>
                      <p className="text-xs text-muted-foreground truncate">{lead.email} · {lead.company}</p>
                    </div>
                    {lead.job_title && (
                      <Badge variant="secondary" className="text-xs hidden md:flex">{lead.job_title}</Badge>
                    )}
                    {lead.industry && (
                      <span className="text-xs text-muted-foreground hidden lg:block">{lead.industry}</span>
                    )}
                    <div className="text-right shrink-0">
                      <p className="text-sm font-semibold text-emerald-400">{Math.round(lead.confidence * 100)}%</p>
                      <p className="text-xs text-muted-foreground">confidence</p>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-12 text-center">
                <Zap className="w-8 h-8 text-muted-foreground/40 mx-auto mb-3" />
                <p className="text-sm text-muted-foreground">No hot leads yet — import and process some leads to see them here.</p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
