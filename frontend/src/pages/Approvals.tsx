import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2, XCircle, PencilLine, ShieldCheck, Bot, FileEdit, Inbox as InboxIcon,
  BookCheck, AlertTriangle, ChevronDown, Globe, Database, User as UserIcon, FileText, Landmark, Target,
} from "lucide-react";
import { toast } from "sonner";
import { approvalsApi, type AutonomyMode, type EmailClaim, type GroundingReport, type PendingEmail } from "../lib/api";
import { Header } from "../components/layout/Header";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { cn, formatDate, apiErrorMessage } from "../lib/utils";
import { useAuthStore } from "../store/authStore";

const MODE_META: Record<AutonomyMode, { label: string; hint: string; icon: typeof Bot }> = {
  draft: { label: "Draft only", hint: "Agent writes, never sends — copy content out manually", icon: FileEdit },
  approve: { label: "Approve first", hint: "Every email waits here for your sign-off before sending", icon: ShieldCheck },
  auto: { label: "Full auto", hint: "Agent sends immediately and follows up on schedule", icon: Bot },
};

function AutonomyDial() {
  const qc = useQueryClient();
  const { user } = useAuthStore();
  const canEdit = user?.role === "admin" || user?.role === "manager";

  const { data } = useQuery({ queryKey: ["autonomy"], queryFn: approvalsApi.getAutonomy });

  const { mutate: setMode } = useMutation({
    mutationFn: approvalsApi.setAutonomy,
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["autonomy"] });
      qc.invalidateQueries({ queryKey: ["approvals"] });
      toast.success(`Autonomy set to "${MODE_META[res.mode].label}"`);
    },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, "Failed to change autonomy mode")),
  });

  return (
    <Card>
      <CardContent className="p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-semibold">Autonomy dial</h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              How much rope does the agent get? Start cautious, graduate to full auto.
            </p>
          </div>
          {data && <Badge variant={data.mode === "auto" ? "success" : "warning"}>{MODE_META[data.mode].label}</Badge>}
        </div>
        <div className="grid grid-cols-3 gap-2">
          {(Object.keys(MODE_META) as AutonomyMode[]).map((mode) => {
            const Meta = MODE_META[mode];
            const active = data?.mode === mode;
            return (
              <button
                key={mode}
                disabled={!canEdit}
                onClick={() => setMode(mode)}
                className={cn(
                  "p-3 rounded-lg border text-left transition-colors",
                  active ? "border-violet-500 bg-violet-500/10" : "border-border hover:bg-secondary/40",
                  !canEdit && "opacity-60 cursor-not-allowed"
                )}
              >
                <Meta.icon className={cn("w-4 h-4 mb-1.5", active ? "text-violet-400" : "text-muted-foreground")} />
                <p className="text-sm font-medium">{Meta.label}</p>
                <p className="text-[11px] text-muted-foreground mt-0.5 leading-snug">{Meta.hint}</p>
              </button>
            );
          })}
        </div>
        {!canEdit && (
          <p className="text-[11px] text-muted-foreground mt-2">Only managers and admins can move the dial.</p>
        )}
      </CardContent>
    </Card>
  );
}

// ── Provenance — every claim in the draft traced to its source ───────────────

const SOURCE_KIND_META: Record<string, { label: string; icon: typeof Globe }> = {
  web_search: { label: "Web search", icon: Globe },
  funding_signal: { label: "Funding data", icon: Landmark },
  enrichment: { label: "Enrichment", icon: Database },
  lead_record: { label: "Lead record", icon: UserIcon },
  icp_check: { label: "ICP check", icon: Target },
  template: { label: "Our template", icon: FileText },
};

function ClaimRow({ claim }: { claim: EmailClaim }) {
  const [showExcerpt, setShowExcerpt] = useState(false);
  const verified = claim.status === "verified";
  const kind = claim.source_kind ? SOURCE_KIND_META[claim.source_kind] : undefined;
  const KindIcon = kind?.icon ?? Globe;

  return (
    <li className="py-2 first:pt-0 last:pb-0">
      <div className="flex items-start gap-2.5">
        {verified ? (
          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0 mt-0.5" aria-label="Verified claim" />
        ) : (
          <AlertTriangle className="w-3.5 h-3.5 text-yellow-400 shrink-0 mt-0.5" aria-label="Unverified claim" />
        )}
        <div className="min-w-0 flex-1">
          <p className="text-xs leading-relaxed">{claim.text}</p>
          {verified ? (
            <button
              type="button"
              onClick={() => setShowExcerpt(!showExcerpt)}
              className="mt-1 inline-flex items-center gap-1.5 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
            >
              <KindIcon className="w-3 h-3 shrink-0" />
              <span className="truncate max-w-[280px]">{kind?.label ?? claim.source_kind} · {claim.source_title}</span>
              <ChevronDown className={cn("w-3 h-3 shrink-0 transition-transform", showExcerpt && "rotate-180")} />
            </button>
          ) : (
            <p className="mt-1 text-[11px] text-yellow-400/80">
              No supporting source found — verify or edit this line before sending
            </p>
          )}
          {verified && showExcerpt && claim.source_excerpt && (
            <blockquote className="mt-1.5 pl-2.5 border-l-2 border-emerald-500/40 text-[11px] text-muted-foreground leading-relaxed">
              {claim.source_excerpt}
            </blockquote>
          )}
        </div>
      </div>
    </li>
  );
}

function GroundingBadge({ report }: { report: GroundingReport }) {
  if (report.claims.length === 0) return null;
  return report.unverified > 0 ? (
    <Badge variant="warning" className="text-[10px] shrink-0 gap-1">
      <AlertTriangle className="w-2.5 h-2.5" />
      {report.unverified} unverified claim{report.unverified > 1 ? "s" : ""}
    </Badge>
  ) : (
    <Badge variant="success" className="text-[10px] shrink-0 gap-1">
      <BookCheck className="w-2.5 h-2.5" />
      all claims sourced
    </Badge>
  );
}

function ClaimsPanel({ report }: { report: GroundingReport }) {
  // Unverified claims are the reason this panel exists — open by default
  // when any need attention; tuck away when everything checks out.
  const [open, setOpen] = useState(report.unverified > 0);
  if (report.claims.length === 0) return null;

  return (
    <div className="rounded-lg border border-border">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-secondary/30 transition-colors rounded-lg"
      >
        <BookCheck className="w-3.5 h-3.5 text-violet-400 shrink-0" />
        <span className="text-xs font-medium">Fact check</span>
        <span className="text-[11px] text-muted-foreground">
          {report.verified}/{report.claims.length} claims traced to a source
        </span>
        <ChevronDown className={cn("w-3.5 h-3.5 text-muted-foreground ml-auto shrink-0 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <ul className="px-3 pb-3 pt-1 divide-y divide-border/60">
          {report.claims.map((claim, i) => (
            <ClaimRow key={i} claim={claim} />
          ))}
        </ul>
      )}
    </div>
  );
}

function EmailCard({ email, draftMode }: { email: PendingEmail; draftMode: boolean }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [subject, setSubject] = useState(email.subject);
  const [body, setBody] = useState(email.body);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["approvals"] });
    qc.invalidateQueries({ queryKey: ["autonomy"] });
  };

  const { mutate: approve, isPending: approving } = useMutation({
    mutationFn: () =>
      approvalsApi.approve(
        email.id,
        editing ? { subject, body } : undefined
      ),
    onSuccess: () => { invalidate(); toast.success("Approved — will send on the next scheduler tick"); },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, "Approval failed")),
  });

  const { mutate: reject, isPending: rejecting } = useMutation({
    mutationFn: () => {
      const reason = window.prompt("Why reject? (optional — feeds prompt tuning)") ?? undefined;
      return approvalsApi.reject(email.id, reason);
    },
    onSuccess: () => { invalidate(); toast.success("Draft rejected"); },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, "Rejection failed")),
  });

  const copyOut = () => {
    navigator.clipboard.writeText(`Subject: ${email.subject}\n\n${email.body}`);
    toast.success("Email copied to clipboard");
  };

  return (
    <Card>
      <CardContent className="p-4 space-y-3">
        <div className="flex items-center gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <p className="text-sm font-medium truncate">{email.lead_name ?? "Unknown lead"}</p>
              <span className="text-xs text-muted-foreground truncate">{email.company}</span>
              <Badge variant="secondary" className="text-[10px] shrink-0">step {email.step_number}</Badge>
              {email.quality_score != null && (
                <Badge
                  variant={email.quality_score >= 0.8 ? "success" : "warning"}
                  className="text-[10px] shrink-0"
                >
                  quality {Math.round(email.quality_score * 100)}
                </Badge>
              )}
              {email.claims && <GroundingBadge report={email.claims} />}
            </div>
            <p className="text-xs text-muted-foreground truncate">{email.lead_email} · drafted {formatDate(email.created_at)}</p>
          </div>
        </div>

        {editing ? (
          <div className="space-y-2">
            <input
              className="w-full h-9 rounded-md border border-input bg-transparent px-3 text-sm"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              aria-label="Email subject"
            />
            <textarea
              className="w-full min-h-[140px] rounded-md border border-input bg-transparent p-3 text-sm font-mono"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              aria-label="Email body"
            />
          </div>
        ) : (
          <div className="rounded-lg bg-secondary/40 border border-border p-3">
            <p className="text-sm font-medium mb-1.5">{email.subject}</p>
            <pre className="text-xs text-muted-foreground whitespace-pre-wrap font-sans leading-relaxed">{email.body}</pre>
          </div>
        )}

        {!editing && email.claims && <ClaimsPanel report={email.claims} />}

        <div className="flex items-center gap-2">
          {draftMode ? (
            <Button size="sm" variant="outline" onClick={copyOut} className="gap-1.5">
              <PencilLine className="w-3.5 h-3.5" />
              Copy to clipboard
            </Button>
          ) : (
            <Button size="sm" variant="gradient" loading={approving} onClick={() => approve()} className="gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5" />
              {editing ? "Approve with edits" : "Approve & send"}
            </Button>
          )}
          <Button size="sm" variant="outline" onClick={() => setEditing(!editing)} className="gap-1.5">
            <PencilLine className="w-3.5 h-3.5" />
            {editing ? "Cancel edit" : "Edit"}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            loading={rejecting}
            onClick={() => reject()}
            className="text-red-400 hover:text-red-400 hover:bg-red-500/10 gap-1.5 ml-auto"
          >
            <XCircle className="w-3.5 h-3.5" />
            Reject
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export default function Approvals() {
  const qc = useQueryClient();
  const { user } = useAuthStore();
  const isManager = user?.role === "admin" || user?.role === "manager";

  const { data, isLoading } = useQuery({
    queryKey: ["approvals"],
    queryFn: approvalsApi.list,
    refetchInterval: 30_000,
  });

  const { mutate: approveAll, isPending: bulkPending } = useMutation({
    mutationFn: approvalsApi.approveAll,
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["approvals"] });
      qc.invalidateQueries({ queryKey: ["autonomy"] });
      toast.success(`Approved ${res.approved} email(s)`);
    },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, "Bulk approval failed")),
  });

  const draftMode = data?.mode === "draft";

  return (
    <div className="flex flex-col min-h-screen">
      <Header
        title="Approvals"
        subtitle="Review what the agent wants to send before it goes out"
      />
      <div className="flex-1 p-8 space-y-6 max-w-4xl animate-fade-in">
        <AutonomyDial />

        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">
            Waiting for review {data ? `(${data.total})` : ""}
          </h3>
          {isManager && !draftMode && (data?.total ?? 0) > 0 && (
            <Button size="sm" variant="outline" loading={bulkPending} onClick={() => approveAll()} className="gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5" />
              Approve all
            </Button>
          )}
        </div>

        {isLoading ? (
          <p className="text-sm text-muted-foreground py-8 text-center">Loading…</p>
        ) : (data?.emails.length ?? 0) === 0 ? (
          <Card>
            <CardContent className="py-12 text-center">
              <InboxIcon className="w-8 h-8 text-muted-foreground mx-auto mb-3" />
              <p className="text-sm font-medium">Queue is clear</p>
              <p className="text-xs text-muted-foreground mt-1">
                {data?.mode === "auto"
                  ? "Full-auto mode — emails send without review. Switch to \"Approve first\" to review drafts here."
                  : "New drafts will appear here as the agent qualifies leads."}
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-3">
            {data!.emails.map((email) => (
              <EmailCard key={email.id} email={email} draftMode={draftMode} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
