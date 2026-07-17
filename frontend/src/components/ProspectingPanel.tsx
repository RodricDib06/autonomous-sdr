import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Users2, Search, Download, ShieldBan, CopyX, MailX, TrendingDown, Wallet } from "lucide-react";
import { toast } from "sonner";
import { prospectingApi, type ProspectingRun } from "../lib/api";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "./ui/card";
import { Badge } from "./ui/badge";
import { VerdictBadge } from "./VerdictBadge";
import { useAuthStore } from "../store/authStore";
import { apiErrorMessage, formatDate } from "../lib/utils";

const REJECTION_META: { key: keyof ProspectingRun["rejected"]; label: string; icon: typeof ShieldBan }[] = [
  { key: "suppressed", label: "suppressed", icon: ShieldBan },
  { key: "duplicate", label: "duplicates", icon: CopyX },
  { key: "undeliverable", label: "undeliverable", icon: MailX },
  { key: "low_score", label: "low score", icon: TrendingDown },
  { key: "budget", label: "over budget", icon: Wallet },
];

function RejectionChips({ rejected }: { rejected: ProspectingRun["rejected"] }) {
  const chips = REJECTION_META.filter(({ key }) => (rejected[key] ?? 0) > 0);
  if (chips.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {chips.map(({ key, label, icon: Icon }) => (
        <Badge key={key} variant="secondary" className="text-[10px] gap-1">
          <Icon className="w-2.5 h-2.5" />
          {rejected[key]} {label}
        </Badge>
      ))}
    </div>
  );
}

export function ProspectingPanel() {
  const qc = useQueryClient();
  const { isManager } = useAuthStore();
  const [industry, setIndustry] = useState("");
  const [seniority, setSeniority] = useState("");
  const [limit, setLimit] = useState(10);
  const [preview, setPreview] = useState<ProspectingRun | null>(null);

  const { data: history } = useQuery({ queryKey: ["prospecting-runs"], queryFn: prospectingApi.list });

  const criteria = {
    ...(industry.trim() ? { industry: industry.trim() } : {}),
    ...(seniority.trim() ? { seniority: seniority.trim() } : {}),
  };

  const { mutate: dryRun, isPending: searching } = useMutation({
    mutationFn: () => prospectingApi.run({ criteria, limit, dry_run: true }),
    onSuccess: (run) => {
      setPreview(run);
      qc.invalidateQueries({ queryKey: ["prospecting-runs"] });
    },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, "Search failed")),
  });

  const { mutate: importRun, isPending: importing } = useMutation({
    mutationFn: () => prospectingApi.run({ criteria, limit }),
    onSuccess: (run) => {
      setPreview(null);
      qc.invalidateQueries({ queryKey: ["prospecting-runs"] });
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      toast.success(`Imported ${run.accepted} lead(s) — they're in the qualification pipeline now`);
    },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, "Import failed")),
  });

  const budget = history?.budget;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-emerald-500/10">
            <Users2 className="w-5 h-5 text-emerald-400" />
          </div>
          <div className="flex-1">
            <CardTitle className="text-sm">Pipeline sourcing</CardTitle>
            <CardDescription>
              The agent finds leads matching a segment, runs them through the quality gates
              (suppression → dedup → verification → scoring), and imports only what survives
            </CardDescription>
          </div>
          {budget && (
            <Badge variant={budget.accepted_today >= budget.max_per_day ? "warning" : "secondary"} className="text-[10px]">
              {budget.accepted_today}/{budget.max_per_day} today
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <form
          className="flex flex-wrap gap-2 items-end"
          onSubmit={(e) => { e.preventDefault(); dryRun(); }}
        >
          <Input placeholder="Industry (e.g. SaaS)" value={industry}
                 onChange={(e) => setIndustry(e.target.value)} className="w-40" aria-label="Industry" />
          <Input placeholder="Seniority (e.g. VP)" value={seniority}
                 onChange={(e) => setSeniority(e.target.value)} className="w-40" aria-label="Seniority" />
          <Input type="number" min={1} max={200} value={limit}
                 onChange={(e) => setLimit(Number(e.target.value))} className="w-24" aria-label="How many" />
          <Button type="submit" size="sm" variant="outline" loading={searching} className="gap-1.5">
            <Search className="w-3.5 h-3.5" />
            Preview
          </Button>
        </form>

        {preview && (
          <div className="space-y-2 animate-fade-in">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <p className="text-xs text-muted-foreground">
                  {preview.candidates?.length ?? 0} candidate(s) passed the gates
                  · {preview.found} found
                </p>
                <RejectionChips rejected={preview.rejected} />
              </div>
              {isManager() && (preview.candidates?.length ?? 0) > 0 && (
                <Button size="sm" variant="gradient" loading={importing} onClick={() => importRun()} className="gap-1.5">
                  <Download className="w-3.5 h-3.5" />
                  Import {preview.candidates!.length} lead(s)
                </Button>
              )}
            </div>
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-muted-foreground border-b border-border bg-secondary/30">
                    <th className="text-left font-medium py-2 px-3">Candidate</th>
                    <th className="text-left font-medium py-2 px-3">Title</th>
                    <th className="text-left font-medium py-2 px-3">Industry</th>
                    <th className="text-left font-medium py-2 px-3">Verdict</th>
                    <th className="text-right font-medium py-2 px-3">Score</th>
                    <th className="text-left font-medium py-2 px-3">Email check</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.candidates?.map((c) => (
                    <tr key={c.email} className="border-b border-border/60 last:border-0">
                      <td className="py-2 px-3">
                        <p className="font-medium">{c.name}</p>
                        <p className="text-muted-foreground">{c.company}</p>
                      </td>
                      <td className="py-2 px-3">{c.job_title}</td>
                      <td className="py-2 px-3">{c.industry}</td>
                      <td className="py-2 px-3"><VerdictBadge verdict={c.verdict} /></td>
                      <td className="py-2 px-3 text-right font-mono">{Math.round(c.score * 100)}</td>
                      <td className="py-2 px-3">
                        <Badge
                          variant={c.verification_status === "valid" ? "success" : "secondary"}
                          className="text-[10px]"
                        >
                          {c.verification_status}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {(history?.runs.length ?? 0) > 0 && (
          <div className="space-y-1.5">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/60">
              Recent runs
            </p>
            {history!.runs.slice(0, 5).map((run) => (
              <div key={run.id} className="flex items-center gap-3 text-xs py-1.5 border-b border-border/40 last:border-0">
                <Badge variant={run.dry_run ? "secondary" : "success"} className="text-[10px] shrink-0">
                  {run.dry_run ? "preview" : `+${run.accepted}`}
                </Badge>
                <span className="text-muted-foreground truncate flex-1">
                  {Object.entries(run.criteria).map(([k, v]) => `${k}: ${v}`).join(" · ") || "any segment"}
                  {" — "}{run.provider}
                </span>
                <RejectionChips rejected={run.rejected} />
                <span className="text-muted-foreground shrink-0">{formatDate(run.created_at)}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
