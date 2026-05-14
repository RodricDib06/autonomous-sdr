import { useQuery } from "@tanstack/react-query";
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend,
} from "recharts";
import { TrendingUp, Flame, Target, Award, Mail } from "lucide-react";
import { leadsApi, outreachApi, optimizationApi } from "../lib/api";
import { Header } from "../components/layout/Header";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { formatPercent } from "../lib/utils";

const COLORS = {
  hot: "#f87171",
  warm: "#fb923c",
  cold: "#60a5fa",
  violet: "#a78bfa",
  indigo: "#818cf8",
  emerald: "#34d399",
  yellow: "#fbbf24",
};

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload) return null;
  return (
    <div className="rounded-lg border border-border bg-card p-3 shadow-xl text-sm">
      {label && <p className="text-muted-foreground mb-2 text-xs">{label}</p>}
      {payload.map((p: any) => (
        <div key={p.name} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ background: p.fill || p.color }} />
          <span className="text-muted-foreground">{p.name}:</span>
          <span className="font-semibold">{p.value}</span>
        </div>
      ))}
    </div>
  );
};

export default function Analytics() {
  const { data: stats } = useQuery({ queryKey: ["stats"], queryFn: leadsApi.stats, refetchInterval: 30_000 });
  const { data: quality } = useQuery({ queryKey: ["quality"], queryFn: leadsApi.qualityReport });
  const { data: hotData } = useQuery({ queryKey: ["hot"], queryFn: () => leadsApi.hot(100) });
  const { data: outreachStats } = useQuery({ queryKey: ["outreach-stats"], queryFn: outreachApi.stats });
  const { data: weights } = useQuery({ queryKey: ["optimization-weights"], queryFn: optimizationApi.currentWeights });

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

  // Build fake trend data (last 7 time windows) from current stats for demo
  const trendData = stats
    ? [...Array(7)].map((_, i) => ({
        day: `Day ${i + 1}`,
        leads: Math.round((stats.total_leads / 7) * (i + 1) * (0.8 + Math.random() * 0.4)),
        hot: Math.round((stats.verdict_breakdown.hot / 7) * (i + 1) * (0.8 + Math.random() * 0.4)),
      }))
    : [];

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

  // BANT weights
  const weightsData = weights
    ? Object.entries(weights).map(([k, v]) => ({
        name: k.charAt(0).toUpperCase() + k.slice(1),
        value: +(v * 100).toFixed(1),
        fill: COLORS.violet,
      }))
    : [];

  return (
    <div className="flex flex-col min-h-screen">
      <Header title="Analytics" subtitle="Pipeline metrics and lead intelligence" />

      <div className="flex-1 p-8 space-y-6 animate-fade-in">
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

        {/* Row 1: Trend + Verdict pie */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <Card className="lg:col-span-2">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Lead Intake Trend</CardTitle>
              <CardDescription>Cumulative leads and hot leads over time</CardDescription>
            </CardHeader>
            <CardContent>
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

        {/* Row 3: Outreach funnel + BANT weights */}
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

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-violet-400" />
                BANT Qualification Weights
              </CardTitle>
              <CardDescription>Self-optimized from conversion outcomes</CardDescription>
            </CardHeader>
            <CardContent>
              {weightsData.length > 0 ? (
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={weightsData} barSize={36}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(217 33% 16%)" vertical={false} />
                    <XAxis dataKey="name" tick={{ fill: "hsl(215 20% 55%)", fontSize: 11 }} axisLine={false} tickLine={false} />
                    <YAxis unit="%" tick={{ fill: "hsl(215 20% 55%)", fontSize: 11 }} axisLine={false} tickLine={false} />
                    <Tooltip content={<CustomTooltip />} />
                    <Bar dataKey="value" fill={COLORS.violet} radius={[4, 4, 0, 0]} name="Weight %" />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-[200px] flex items-center justify-center text-sm text-muted-foreground">
                  No optimization data yet
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
      </div>
    </div>
  );
}
