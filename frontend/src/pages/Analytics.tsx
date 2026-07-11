import { useQuery } from "@tanstack/react-query";
import {
  AreaChart, Area, BarChart, Bar, LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from "recharts";
import { TrendingUp, Flame, Target, Award, Mail, Sparkles, BarChart2, Zap, Users, DollarSign } from "lucide-react";
import { leadsApi, outreachApi, optimizationApi, marketApi, analyticsApi, roiApi } from "../lib/api";
import { Header } from "../components/layout/Header";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { formatPercent, cn } from "../lib/utils";

const COLORS = {
  hot: "#f87171",
  warm: "#fb923c",
  cold: "#60a5fa",
  violet: "#a78bfa",
  indigo: "#818cf8",
  emerald: "#34d399",
  yellow: "#fbbf24",
};

const WEIGHT_COLORS: Record<string, string> = {
  budget: "#a78bfa",
  authority: "#34d399",
  need: "#fb923c",
  timeline: "#60a5fa",
};

interface TooltipPayloadItem {
  name: string;
  value: number | string;
  fill?: string;
  color?: string;
  unit?: string;
}

const CustomTooltip = ({ active, payload, label }: { active?: boolean; payload?: TooltipPayloadItem[]; label?: string }) => {
  if (!active || !payload) return null;
  return (
    <div className="rounded-lg border border-border bg-card p-3 shadow-xl text-sm">
      {label && <p className="text-muted-foreground mb-2 text-xs">{label}</p>}
      {payload.map((p) => (
        <div key={p.name} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ background: p.fill || p.color }} />
          <span className="text-muted-foreground">{p.name}:</span>
          <span className="font-semibold">{p.value}{p.unit ?? ""}</span>
        </div>
      ))}
    </div>
  );
};

function ROIPanel() {
  const { data: roi } = useQuery({ queryKey: ["roi"], queryFn: () => roiApi.get(), staleTime: 120_000 });

  if (!roi) return null;
  const { activity, unit_economics: ue, projections } = roi;
  const fmtUsd = (v: number | null) =>
    v == null ? "—" : v >= 100 ? `$${Math.round(v).toLocaleString()}` : `$${v.toFixed(v < 1 ? 3 : 2)}`;

  return (
    <Card className="border-emerald-500/20 bg-gradient-to-br from-emerald-500/5 to-transparent">
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-emerald-500/10">
            <DollarSign className="w-5 h-5 text-emerald-400" />
          </div>
          <div>
            <CardTitle className="text-sm">ROI — AI vs human SDR</CardTitle>
            <CardDescription>
              Computed from your last {roi.window_days} days of pipeline activity
              (assumes ${roi.assumptions.sdr_annual_cost_usd.toLocaleString()}/yr fully-loaded SDR)
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <p className="text-xs text-muted-foreground">Cost per qualified lead</p>
            <p className="text-xl font-semibold text-emerald-400">{fmtUsd(ue.ai_cost_per_lead_usd)}</p>
            <p className="text-[11px] text-muted-foreground">vs {fmtUsd(ue.human_cost_per_lead_usd)} human</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Cost per meeting booked</p>
            <p className="text-xl font-semibold">{fmtUsd(ue.cost_per_meeting_usd)}</p>
            <p className="text-[11px] text-muted-foreground">{activity.meetings_booked} meetings in window</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Projected annual savings</p>
            <p className="text-xl font-semibold text-emerald-400">{fmtUsd(projections.projected_annual_savings_usd)}</p>
            <p className="text-[11px] text-muted-foreground">
              at {projections.annualized_lead_volume.toLocaleString()} leads/yr
            </p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Closed pipeline value</p>
            <p className="text-xl font-semibold">{fmtUsd(projections.pipeline_value_usd)}</p>
            <p className="text-[11px] text-muted-foreground">
              {activity.conversions} wins · LLM spend {fmtUsd(activity.llm_cost_usd)}
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function Analytics() {
  const { data: stats } = useQuery({ queryKey: ["stats"], queryFn: leadsApi.stats, refetchInterval: 30_000 });
  const { data: quality } = useQuery({ queryKey: ["quality"], queryFn: leadsApi.qualityReport });
  const { data: hotData } = useQuery({ queryKey: ["hot"], queryFn: () => leadsApi.hot(100) });
  const { data: outreachStats } = useQuery({ queryKey: ["outreach-stats"], queryFn: outreachApi.stats });
  const { data: trend } = useQuery({ queryKey: ["lead-trend"], queryFn: () => leadsApi.trend(30) });
  const { data: optHistory } = useQuery({
    queryKey: ["optimization-history"],
    queryFn: () => optimizationApi.history(20),
  });

  const { data: marketIntel } = useQuery({
    queryKey: ["market-intelligence"],
    queryFn: marketApi.intelligence,
    staleTime: 120_000,
  });

  const { data: velocity } = useQuery({
    queryKey: ["pipeline-velocity"],
    queryFn: analyticsApi.pipelineVelocity,
    staleTime: 60_000,
  });

  const { data: repPerf } = useQuery({
    queryKey: ["rep-performance"],
    queryFn: analyticsApi.repPerformance,
    staleTime: 60_000,
  });

  const verdictData = stats
    ? [
        { name: "Hot", value: stats.verdict_breakdown.hot, fill: COLORS.hot },
        { name: "Warm", value: stats.verdict_breakdown.warm, fill: COLORS.warm },
        { name: "Cold", value: stats.verdict_breakdown.cold, fill: COLORS.cold },
      ]
    : [];

  const pipelineData = stats
    ? [
        { name: "Total", value: stats.total_leads, fill: COLORS.violet },
        { name: "Completed", value: stats.completed, fill: COLORS.indigo },
        { name: "Failed", value: stats.failed, fill: COLORS.hot },
        { name: "Processing", value: stats.processing, fill: COLORS.yellow },
      ]
    : [];

  const qualityData = quality?.quality_distribution
    ? [
        { name: "Excellent (80-100)", value: quality.quality_distribution.excellent, fill: COLORS.emerald },
        { name: "Good (60-80)", value: quality.quality_distribution.good, fill: "#a3e635" },
        { name: "Fair (40-60)", value: quality.quality_distribution.fair, fill: COLORS.yellow },
        { name: "Poor (<40)", value: quality.quality_distribution.poor, fill: COLORS.hot },
      ]
    : [];

  // Real trend data from the database
  const trendData = trend?.data.map((d) => ({
    day: d.day.slice(5), // MM-DD
    leads: d.total,
    hot: d.hot,
  })) ?? [];

  // Industry breakdown from hot leads
  const industryMap: Record<string, number> = {};
  hotData?.hot_leads.forEach((l) => {
    if (l.industry) industryMap[l.industry] = (industryMap[l.industry] ?? 0) + 1;
  });
  const industryData = Object.entries(industryMap)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([name, value]) => ({ name, value, fill: COLORS.violet }));

  // Seniority distribution from hot leads
  const seniorityMap: Record<string, number> = {};
  hotData?.hot_leads.forEach((l) => {
    if (l.seniority) seniorityMap[l.seniority] = (seniorityMap[l.seniority] ?? 0) + 1;
  });
  const seniorityData = Object.entries(seniorityMap)
    .sort((a, b) => b[1] - a[1])
    .map(([name, value]) => ({ name, value, fill: COLORS.indigo }));

  // Outreach funnel
  const funnelData = outreachStats
    ? [
        { name: "Sent", value: outreachStats.total_sent, fill: COLORS.violet },
        { name: "Opened", value: outreachStats.total_opened, fill: COLORS.indigo },
        { name: "Replied", value: outreachStats.total_replied, fill: COLORS.emerald },
      ]
    : [];

  // BANT weights evolution — transform optimization history into a time series
  // Each run has new_weights: { budget: 0.3, authority: 0.25, need: 0.25, timeline: 0.2 }
  const weightsEvolution: Array<Record<string, string | number>> = (optHistory?.runs ?? [])
    .slice()
    .reverse()
    .map((run, i) => ({
      run: `Run ${i + 1}`,
      ...Object.fromEntries(
        Object.entries(run.new_weights ?? {}).map(([k, v]) => [k, +(Number(v) * 100).toFixed(1)])
      ),
    }));

  const weightKeys = weightsEvolution.length > 0
    ? Object.keys(weightsEvolution[0]).filter((k) => k !== "run")
    : [];

  // Single-run fallback: show current weights as a bar chart
  const singleWeightsData = weightsEvolution.length === 1
    ? weightKeys.map((k) => ({ name: k.charAt(0).toUpperCase() + k.slice(1), value: weightsEvolution[0][k] as number, fill: WEIGHT_COLORS[k] ?? COLORS.violet }))
    : [];

  return (
    <div className="flex flex-col min-h-screen">
      <Header title="Analytics" subtitle="Pipeline metrics and lead intelligence" />

      <div className="flex-1 p-8 space-y-6 animate-fade-in">
        <ROIPanel />

        {/* Summary pills */}
        <div className="flex flex-wrap gap-3">
          {[
            { label: "Success Rate", value: stats ? formatPercent(stats.success_rate) : "—", icon: Award, color: "text-emerald-400" },
            { label: "Hot Rate", value: stats && stats.completed ? formatPercent(stats.verdict_breakdown.hot / stats.completed) : "—", icon: Flame, color: "text-red-400" },
            { label: "Avg Quality", value: quality ? `${Math.round((quality.avg_quality_score ?? 0) * 100)}` : "—", icon: Target, color: "text-violet-400" },
            { label: "Avg Completeness", value: quality ? `${Math.round((quality.avg_completeness_score ?? 0) * 100)}` : "—", icon: TrendingUp, color: "text-indigo-400" },
          ].map(({ label, value, icon: Icon, color }) => (
            <div key={label} className="flex items-center gap-3 px-4 py-2.5 rounded-xl border border-border bg-card">
              <Icon className={`w-4 h-4 ${color}`} />
              <span className="text-sm text-muted-foreground">{label}</span>
              <span className="font-semibold">{value}</span>
            </div>
          ))}
        </div>

        {/* Row 1: Real trend + Verdict pie */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <Card className="lg:col-span-2">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Lead Intake — Last 30 Days</CardTitle>
              <CardDescription>Daily leads ingested and hot leads qualified</CardDescription>
            </CardHeader>
            <CardContent>
              {trendData.length > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <AreaChart data={trendData}>
                    <defs>
                      <linearGradient id="gradLeads" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={COLORS.violet} stopOpacity={0.3} />
                        <stop offset="95%" stopColor={COLORS.violet} stopOpacity={0} />
                      </linearGradient>
                      <linearGradient id="gradHot" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={COLORS.hot} stopOpacity={0.3} />
                        <stop offset="95%" stopColor={COLORS.hot} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(217 33% 16%)" vertical={false} />
                    <XAxis dataKey="day" tick={{ fill: "hsl(215 20% 55%)", fontSize: 11 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: "hsl(215 20% 55%)", fontSize: 11 }} axisLine={false} tickLine={false} />
                    <Tooltip content={<CustomTooltip />} />
                    <Area type="monotone" dataKey="leads" name="Total Leads" stroke={COLORS.violet} fill="url(#gradLeads)" strokeWidth={2} dot={false} />
                    <Area type="monotone" dataKey="hot" name="Hot Leads" stroke={COLORS.hot} fill="url(#gradHot)" strokeWidth={2} dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-[220px] flex items-center justify-center text-sm text-muted-foreground">
                  No lead data yet — import leads to see the trend
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Verdict Distribution</CardTitle>
              <CardDescription>Qualification outcomes</CardDescription>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={180}>
                <PieChart>
                  <Pie data={verdictData} cx="50%" cy="50%" outerRadius={70} innerRadius={40} paddingAngle={3} dataKey="value">
                    {verdictData.map((e, i) => <Cell key={i} fill={e.fill} stroke="transparent" />)}
                  </Pie>
                  <Tooltip content={<CustomTooltip />} />
                </PieChart>
              </ResponsiveContainer>
              <div className="flex justify-center gap-4 text-xs mt-1">
                {verdictData.map((d) => (
                  <div key={d.name} className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full" style={{ background: d.fill }} />
                    <span className="text-muted-foreground">{d.name} <span className="text-foreground font-medium">{d.value}</span></span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Row 2: Quality + Pipeline */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Data Quality Distribution</CardTitle>
              <CardDescription>
                {quality ? `${quality.total_leads} leads scored` : "Awaiting data"}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={qualityData} barSize={40}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(217 33% 16%)" vertical={false} />
                  <XAxis dataKey="name" tick={{ fill: "hsl(215 20% 55%)", fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: "hsl(215 20% 55%)", fontSize: 11 }} axisLine={false} tickLine={false} />
                  <Tooltip content={<CustomTooltip />} />
                  {qualityData.map((d, i) => (
                    <Bar key={i} dataKey="value" fill={d.fill} radius={[4, 4, 0, 0]} name={d.name} />
                  ))}
                  <Bar dataKey="value" fill={COLORS.violet} radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Pipeline Overview</CardTitle>
              <CardDescription>Processing status breakdown</CardDescription>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={pipelineData} layout="vertical" barSize={18}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(217 33% 16%)" horizontal={false} />
                  <XAxis type="number" tick={{ fill: "hsl(215 20% 55%)", fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="name" tick={{ fill: "hsl(215 20% 55%)", fontSize: 12 }} axisLine={false} tickLine={false} width={80} />
                  <Tooltip content={<CustomTooltip />} />
                  {pipelineData.map((d, i) => (
                    <Bar key={i} dataKey="value" fill={d.fill} radius={[0, 4, 4, 0]} name={d.name} />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </div>

        {/* Row 3: Outreach funnel + BANT weights evolution */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <Mail className="w-4 h-4 text-violet-400" />
                Outreach Funnel
              </CardTitle>
              <CardDescription>Email engagement across all sequences</CardDescription>
            </CardHeader>
            <CardContent>
              {funnelData.length > 0 && funnelData[0].value > 0 ? (
                <>
                  <ResponsiveContainer width="100%" height={180}>
                    <BarChart data={funnelData} barSize={48}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(217 33% 16%)" vertical={false} />
                      <XAxis dataKey="name" tick={{ fill: "hsl(215 20% 55%)", fontSize: 11 }} axisLine={false} tickLine={false} />
                      <YAxis tick={{ fill: "hsl(215 20% 55%)", fontSize: 11 }} axisLine={false} tickLine={false} />
                      <Tooltip content={<CustomTooltip />} />
                      {funnelData.map((d, i) => (
                        <Bar key={i} dataKey="value" fill={d.fill} radius={[4, 4, 0, 0]} name={d.name} />
                      ))}
                    </BarChart>
                  </ResponsiveContainer>
                  <div className="grid grid-cols-3 gap-2 mt-2 text-center">
                    {outreachStats && [
                      { label: "Open rate", value: formatPercent(outreachStats.open_rate) },
                      { label: "Reply rate", value: formatPercent(outreachStats.reply_rate) },
                      { label: "Sent", value: outreachStats.total_sent },
                    ].map(({ label, value }) => (
                      <div key={label} className="rounded-lg bg-secondary/30 py-2">
                        <p className="text-sm font-semibold">{value}</p>
                        <p className="text-[10px] text-muted-foreground">{label}</p>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <div className="h-[200px] flex items-center justify-center text-sm text-muted-foreground">
                  No outreach data yet
                </div>
              )}
            </CardContent>
          </Card>

          {/* BANT Weights Evolution — shows the self-optimization in action */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-violet-400" />
                BANT Weight Evolution
              </CardTitle>
              <CardDescription>
                How qualification weights shifted across {optHistory?.count ?? 0} optimization runs
              </CardDescription>
            </CardHeader>
            <CardContent>
              {weightsEvolution.length > 1 ? (
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={weightsEvolution}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(217 33% 16%)" vertical={false} />
                    <XAxis dataKey="run" tick={{ fill: "hsl(215 20% 55%)", fontSize: 11 }} axisLine={false} tickLine={false} />
                    <YAxis unit="%" tick={{ fill: "hsl(215 20% 55%)", fontSize: 11 }} axisLine={false} tickLine={false} domain={[0, 60]} />
                    <Tooltip content={<CustomTooltip />} />
                    <Legend wrapperStyle={{ fontSize: "11px", color: "hsl(215 20% 55%)" }} />
                    {weightKeys.map((key) => (
                      <Line
                        key={key}
                        type="monotone"
                        dataKey={key}
                        name={key.charAt(0).toUpperCase() + key.slice(1)}
                        stroke={WEIGHT_COLORS[key] ?? COLORS.violet}
                        strokeWidth={2}
                        dot={{ r: 3, fill: WEIGHT_COLORS[key] ?? COLORS.violet }}
                        unit="%"
                      />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              ) : singleWeightsData.length > 0 ? (
                <>
                  <ResponsiveContainer width="100%" height={160}>
                    <BarChart data={singleWeightsData} barSize={36}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(217 33% 16%)" vertical={false} />
                      <XAxis dataKey="name" tick={{ fill: "hsl(215 20% 55%)", fontSize: 11 }} axisLine={false} tickLine={false} />
                      <YAxis unit="%" tick={{ fill: "hsl(215 20% 55%)", fontSize: 11 }} axisLine={false} tickLine={false} />
                      <Tooltip content={<CustomTooltip />} />
                      {singleWeightsData.map((d, i) => (
                        <Bar key={i} dataKey="value" fill={d.fill} radius={[4, 4, 0, 0]} name={d.name} />
                      ))}
                    </BarChart>
                  </ResponsiveContainer>
                  <p className="text-[11px] text-muted-foreground text-center mt-2">
                    Evolution chart unlocks after 2+ optimization runs
                  </p>
                </>
              ) : (
                <div className="h-[200px] flex items-center justify-center text-sm text-muted-foreground">
                  No optimization runs yet — run the optimizer to see weight evolution
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Row 4: Industry + Seniority */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Top Industries</CardTitle>
              <CardDescription>From hot leads</CardDescription>
            </CardHeader>
            <CardContent>
              {industryData.length > 0 ? (
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={industryData} layout="vertical" barSize={14}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(217 33% 16%)" horizontal={false} />
                    <XAxis type="number" tick={{ fill: "hsl(215 20% 55%)", fontSize: 11 }} axisLine={false} tickLine={false} />
                    <YAxis type="category" dataKey="name" tick={{ fill: "hsl(215 20% 55%)", fontSize: 11 }} axisLine={false} tickLine={false} width={90} />
                    <Tooltip content={<CustomTooltip />} />
                    <Bar dataKey="value" fill={COLORS.violet} radius={[0, 4, 4, 0]} name="Leads" />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-[200px] flex items-center justify-center text-sm text-muted-foreground">
                  No enriched leads yet
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Seniority Breakdown</CardTitle>
              <CardDescription>Decision-maker coverage</CardDescription>
            </CardHeader>
            <CardContent>
              {seniorityData.length > 0 ? (
                <ResponsiveContainer width="100%" height={200}>
                  <PieChart>
                    <Pie data={seniorityData} cx="50%" cy="50%" outerRadius={80} innerRadius={45} paddingAngle={2} dataKey="value">
                      {seniorityData.map((_, i) => (
                        <Cell key={i} fill={[COLORS.violet, COLORS.indigo, COLORS.hot, COLORS.warm, COLORS.emerald][i % 5]} stroke="transparent" />
                      ))}
                    </Pie>
                    <Tooltip content={<CustomTooltip />} />
                    <Legend wrapperStyle={{ fontSize: "11px", color: "hsl(215 20% 55%)" }} />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-[200px] flex items-center justify-center text-sm text-muted-foreground">
                  No enriched leads yet
                </div>
              )}
            </CardContent>
          </Card>
        </div>
        {/* Row 5: Pipeline Velocity */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center gap-2">
                <Zap className="w-4 h-4 text-yellow-400" />
                <CardTitle className="text-sm">Pipeline Velocity</CardTitle>
              </div>
              <CardDescription>
                How fast leads move from creation to qualification to close
                {velocity ? ` · ${velocity.total_complete} completed leads` : ""}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {velocity ? (
                <div className="space-y-4">
                  {[
                    { label: "Time to Qualify", stats: velocity.time_to_qualify_hours, color: "text-violet-400" },
                    { label: "Time to Book", stats: velocity.time_to_book_hours, color: "text-emerald-400" },
                    { label: "Time to Close", stats: velocity.time_to_close_hours, color: "text-orange-400" },
                  ].map(({ label, stats, color }) => (
                    <div key={label}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs text-muted-foreground">{label}</span>
                        <span className="text-xs text-muted-foreground">{stats.count} leads</span>
                      </div>
                      {stats.avg !== null ? (
                        <div className="grid grid-cols-3 gap-2 text-center">
                          {[
                            { key: "Avg", val: stats.avg },
                            { key: "P50", val: stats.p50 },
                            { key: "P90", val: stats.p90 },
                          ].map(({ key, val }) => (
                            <div key={key} className="rounded-lg bg-secondary/30 py-2">
                              <p className={`text-sm font-semibold ${color}`}>
                                {val !== null ? `${val}h` : "—"}
                              </p>
                              <p className="text-[10px] text-muted-foreground">{key}</p>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-xs text-muted-foreground italic">No data yet</p>
                      )}
                    </div>
                  ))}
                  <div className="grid grid-cols-2 gap-2 pt-2 border-t border-border">
                    <div className="text-center">
                      <p className="text-sm font-semibold text-emerald-400">{(velocity.booking_rate * 100).toFixed(1)}%</p>
                      <p className="text-[10px] text-muted-foreground">Booking rate</p>
                    </div>
                    <div className="text-center">
                      <p className="text-sm font-semibold text-orange-400">{(velocity.close_rate * 100).toFixed(1)}%</p>
                      <p className="text-[10px] text-muted-foreground">Close rate</p>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="h-[200px] flex items-center justify-center text-sm text-muted-foreground">
                  No completed leads yet
                </div>
              )}
            </CardContent>
          </Card>

          {/* Row 5b: Rep Leaderboard */}
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center gap-2">
                <Users className="w-4 h-4 text-indigo-400" />
                <CardTitle className="text-sm">Rep Leaderboard</CardTitle>
              </div>
              <CardDescription>
                Performance by rep — conversions, hot leads, meetings booked
              </CardDescription>
            </CardHeader>
            <CardContent>
              {repPerf && repPerf.reps.length > 0 ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-border">
                        <th className="py-2 text-left font-semibold text-muted-foreground">Rep</th>
                        <th className="py-2 text-right font-semibold text-muted-foreground">Leads</th>
                        <th className="py-2 text-right font-semibold text-muted-foreground">Hot</th>
                        <th className="py-2 text-right font-semibold text-muted-foreground">Booked</th>
                        <th className="py-2 text-right font-semibold text-muted-foreground">Won</th>
                        <th className="py-2 text-right font-semibold text-muted-foreground">Conv%</th>
                      </tr>
                    </thead>
                    <tbody>
                      {repPerf.reps.map((rep, i) => (
                        <tr key={rep.rep_id} className="border-b border-border/40 hover:bg-secondary/20">
                          <td className="py-2.5">
                            <div className="flex items-center gap-2">
                              {i === 0 && <span className="text-yellow-400 text-[10px]">🥇</span>}
                              {i === 1 && <span className="text-slate-400 text-[10px]">🥈</span>}
                              {i === 2 && <span className="text-orange-400 text-[10px]">🥉</span>}
                              <span className="font-medium truncate max-w-[100px]" title={rep.rep_email}>
                                {rep.rep_email.split("@")[0]}
                              </span>
                            </div>
                          </td>
                          <td className="py-2.5 text-right tabular-nums">{rep.leads_assigned}</td>
                          <td className="py-2.5 text-right tabular-nums">
                            <span className={rep.hot_qualified > 0 ? "text-red-400 font-semibold" : "text-muted-foreground"}>
                              {rep.hot_qualified}
                            </span>
                          </td>
                          <td className="py-2.5 text-right tabular-nums">{rep.meetings_booked}</td>
                          <td className="py-2.5 text-right tabular-nums">
                            <span className={rep.conversions > 0 ? "text-emerald-400 font-semibold" : "text-muted-foreground"}>
                              {rep.conversions}
                            </span>
                          </td>
                          <td className="py-2.5 text-right tabular-nums">
                            <span className={rep.conversion_rate >= 0.3 ? "text-emerald-400" : rep.conversion_rate >= 0.1 ? "text-orange-400" : "text-muted-foreground"}>
                              {(rep.conversion_rate * 100).toFixed(0)}%
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="h-[200px] flex items-center justify-center text-sm text-muted-foreground">
                  No rep data yet — assign leads to reps to see the leaderboard
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Row 6: Market Intelligence */}
        {marketIntel && marketIntel.segments.length > 0 && (
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center gap-2">
                <BarChart2 className="w-4 h-4 text-violet-400" />
                <CardTitle className="text-sm">Market Intelligence</CardTitle>
              </div>
              <CardDescription>
                Segments converting at highest rate vs {Math.round((marketIntel.global_stats.global_hot_rate) * 100)}% baseline
                · {marketIntel.global_stats.total} leads analysed
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="py-2 text-left font-semibold text-muted-foreground">Industry</th>
                      <th className="py-2 text-left font-semibold text-muted-foreground">Seniority</th>
                      <th className="py-2 text-right font-semibold text-muted-foreground">Leads</th>
                      <th className="py-2 text-right font-semibold text-muted-foreground">Hot rate</th>
                      <th className="py-2 text-right font-semibold text-muted-foreground">Lift</th>
                    </tr>
                  </thead>
                  <tbody>
                    {marketIntel.segments.slice(0, 10).map((seg, i) => (
                      <tr key={i} className="border-b border-border/40 hover:bg-secondary/20">
                        <td className="py-2.5 font-medium">{seg.industry}</td>
                        <td className="py-2.5 text-muted-foreground">{seg.seniority}</td>
                        <td className="py-2.5 text-right tabular-nums">{seg.total}</td>
                        <td className="py-2.5 text-right tabular-nums">
                          <span className={seg.hot_rate >= 0.5 ? "text-emerald-400 font-semibold" : seg.hot_rate >= 0.3 ? "text-orange-400" : "text-muted-foreground"}>
                            {Math.round(seg.hot_rate * 100)}%
                          </span>
                        </td>
                        <td className="py-2.5 text-right tabular-nums">
                          <span className={cn(
                            "font-semibold",
                            seg.lift >= 2 ? "text-emerald-400" : seg.lift >= 1.3 ? "text-orange-400" : "text-muted-foreground"
                          )}>
                            {seg.lift.toFixed(1)}×
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
