import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Search, Filter, Download, X, ChevronRight,
  Building2, Tag, Archive, Trash2, RefreshCw,
} from "lucide-react";
import { toast } from "sonner";
import { leadsApi } from "../lib/api";
import type { LeadDetail } from "../types";
import { Header } from "../components/layout/Header";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Badge } from "../components/ui/badge";
import { Card } from "../components/ui/card";
import { VerdictBadge } from "../components/VerdictBadge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Progress } from "../components/ui/progress";
import { formatDate, scoreColor, cn } from "../lib/utils";

const STATUS_COLORS: Record<string, string> = {
  complete: "success",
  processing: "warning",
  pending: "secondary",
  failed: "destructive",
};

function LeadDetailPanel({ lead, onClose }: { lead: LeadDetail; onClose: () => void }) {
  const bant = lead.verdict?.bant_scores;

  return (
    <div className="fixed inset-y-0 right-0 z-40 w-[480px] bg-card border-l border-border shadow-2xl flex flex-col animate-slide-in">
      {/* Header */}
      <div className="flex items-center justify-between p-6 border-b border-border">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-gradient-to-br from-violet-600 to-indigo-600 flex items-center justify-center text-white font-semibold">
            {lead.name.slice(0, 2).toUpperCase()}
          </div>
          <div>
            <h2 className="font-semibold">{lead.name}</h2>
            <p className="text-sm text-muted-foreground">{lead.email}</p>
          </div>
        </div>
        <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-secondary transition-colors">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Verdict */}
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

        {/* Basic info */}
        <section className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Contact</h3>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <p className="text-muted-foreground text-xs mb-0.5">Company</p>
              <p className="font-medium">{lead.company}</p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs mb-0.5">Source</p>
              <p className="font-medium capitalize">{lead.source ?? "—"}</p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs mb-0.5">Status</p>
              <Badge variant={STATUS_COLORS[lead.status] as any}>{lead.status}</Badge>
            </div>
            <div>
              <p className="text-muted-foreground text-xs mb-0.5">Created</p>
              <p className="font-medium">{formatDate(lead.created_at)}</p>
            </div>
          </div>
        </section>

        {/* Enrichment */}
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

        {/* BANT scores */}
        {bant && Object.keys(bant).length > 0 && (
          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">BANT Analysis</h3>
            <div className="space-y-2.5">
              {Object.entries(bant).map(([key, score]) => {
                const s = typeof score === "number" ? score : 0.5;
                const colorMap =
                  s >= 0.7 ? "bg-emerald-500" :
                  s >= 0.4 ? "bg-orange-400" :
                  "bg-red-500";
                const labelColorMap =
                  s >= 0.7 ? "text-emerald-400" :
                  s >= 0.4 ? "text-orange-400" :
                  "text-red-400";
                return (
                  <div key={key} className="space-y-1">
                    <div className="flex justify-between text-xs">
                      <span className="capitalize text-muted-foreground">{key}</span>
                      <span className={cn("font-medium", labelColorMap)}>
                        {Math.round(s * 100)}%
                      </span>
                    </div>
                    <Progress
                      value={s * 100}
                      className="h-1.5"
                      indicatorClassName={colorMap}
                    />
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* Reasoning */}
        {lead.verdict?.reasoning && (
          <section className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">AI Reasoning</h3>
            <p className="text-sm text-muted-foreground leading-relaxed bg-secondary/50 rounded-lg p-3">
              {lead.verdict.reasoning}
            </p>
          </section>
        )}

        {/* Quality */}
        <section className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Data Quality</h3>
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg bg-secondary/50 p-3 text-center">
              <p className={cn("text-2xl font-bold", scoreColor(lead.data_quality_score))}>
                {lead.data_quality_score != null ? Math.round(lead.data_quality_score * 100) : "—"}
              </p>
              <p className="text-xs text-muted-foreground mt-0.5">Quality Score</p>
            </div>
            <div className="rounded-lg bg-secondary/50 p-3 text-center">
              <p className={cn("text-2xl font-bold", scoreColor(lead.completeness_score))}>
                {lead.completeness_score != null ? Math.round(lead.completeness_score * 100) : "—"}
              </p>
              <p className="text-xs text-muted-foreground mt-0.5">Completeness</p>
            </div>
          </div>
        </section>

        {/* Tags */}
        {lead.tags && lead.tags.length > 0 && (
          <section className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Tags</h3>
            <div className="flex flex-wrap gap-1.5">
              {lead.tags.map((t) => (
                <Badge key={t} variant="default" className="text-xs gap-1">
                  <Tag className="w-2.5 h-2.5" />
                  {t}
                </Badge>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

export default function Leads() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [selectedLead, setSelectedLead] = useState<LeadDetail | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [page, setPage] = useState(0);
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

  const failedCount = leads.filter((l) => l.status === "failed").length;

  const filtered = leads.filter((l) => {
    const q = search.toLowerCase();
    const matchSearch = !q || l.name.toLowerCase().includes(q) || l.email.toLowerCase().includes(q) || l.company.toLowerCase().includes(q);
    const matchStatus = statusFilter === "all" || l.status === statusFilter;
    return matchSearch && matchStatus && !l.archived;
  });

  const toggleSelect = (id: string) => {
    const next = new Set(selectedIds);
    next.has(id) ? next.delete(id) : next.add(id);
    setSelectedIds(next);
  };

  const handleExport = async () => {
    try {
      const blob = await leadsApi.export("csv");
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "leads.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("Export failed");
    }
  };

  return (
    <div className="flex flex-col min-h-screen">
      <Header
        title="Leads"
        subtitle={`${filtered.length} leads`}
        actions={
          <div className="flex items-center gap-2">
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
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              placeholder="Search by name, email or company…"
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
        </div>

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
                  {["Name", "Company", "Status", "Verdict", "Quality", "Created", ""].map((h) => (
                    <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {isLoading ? (
                  [...Array(8)].map((_, i) => (
                    <tr key={i} className="border-b border-border/50">
                      <td colSpan={8} className="p-3">
                        <div className="skeleton h-9 rounded" />
                      </td>
                    </tr>
                  ))
                ) : filtered.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="p-12 text-center text-muted-foreground">
                      No leads found
                    </td>
                  </tr>
                ) : (
                  filtered.map((lead) => (
                    <tr
                      key={lead.id}
                      className="border-b border-border/50 hover:bg-secondary/20 transition-colors group cursor-pointer"
                      onClick={() => loadDetail(lead.id)}
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
                        <Badge variant={STATUS_COLORS[lead.status] as any} className="capitalize">
                          {lead.status}
                        </Badge>
                      </td>
                      <td className="px-4 py-3">
                        <VerdictBadge verdict={lead.final_verdict} />
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
          <span>Showing {filtered.length} leads</span>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Prev</Button>
            <Button size="sm" variant="outline" disabled={leads.length < PAGE_SIZE} onClick={() => setPage((p) => p + 1)}>Next</Button>
          </div>
        </div>
      </div>

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
