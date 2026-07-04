import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, PencilLine, Globe2, Clock, Mail } from "lucide-react";
import { toast } from "sonner";
import { sequencesApi, type Sequence, type SequenceStep } from "../lib/api";
import { Header } from "../components/layout/Header";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "../components/ui/dialog";
import { apiErrorMessage } from "../lib/utils";
import { useAuthStore } from "../store/authStore";

const EMPTY_STEP = (n: number): SequenceStep => ({
  step: n,
  delay_days: n === 1 ? 0 : 3,
  subject_template: "",
  body_template: "",
});

function StepEditor({ steps, onChange }: { steps: SequenceStep[]; onChange: (s: SequenceStep[]) => void }) {
  const update = (i: number, patch: Partial<SequenceStep>) => {
    const next = steps.map((s, idx) => (idx === i ? { ...s, ...patch } : s));
    onChange(next);
  };
  const removeStep = (i: number) => {
    const next = steps.filter((_, idx) => idx !== i).map((s, idx) => ({ ...s, step: idx + 1 }));
    onChange(next);
  };

  return (
    <div className="space-y-3">
      {steps.map((step, i) => (
        <div key={i} className="p-3 rounded-lg border border-border space-y-2">
          <div className="flex items-center gap-2">
            <Badge variant="secondary" className="text-[10px]">Step {step.step}</Badge>
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Clock className="w-3 h-3" />
              after
              <input
                type="number"
                min={0}
                max={90}
                value={step.delay_days}
                onChange={(e) => update(i, { delay_days: Number(e.target.value) })}
                className="w-14 h-6 rounded border border-input bg-transparent px-1.5 text-xs"
                aria-label={`Step ${step.step} delay in days`}
              />
              day(s)
            </div>
            {steps.length > 1 && (
              <button
                type="button"
                onClick={() => removeStep(i)}
                className="ml-auto p-1 rounded text-red-400 hover:bg-red-500/10"
                aria-label={`Remove step ${step.step}`}
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
          <Input
            placeholder="Subject — e.g. Quick question about {company}"
            value={step.subject_template}
            onChange={(e) => update(i, { subject_template: e.target.value })}
          />
          <textarea
            placeholder={"Body — Hi {first_name}, …"}
            value={step.body_template}
            onChange={(e) => update(i, { body_template: e.target.value })}
            className="w-full min-h-[90px] rounded-md border border-input bg-transparent p-2.5 text-sm"
          />
        </div>
      ))}
      {steps.length < 10 && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => onChange([...steps, EMPTY_STEP(steps.length + 1)])}
          className="gap-1.5"
        >
          <Plus className="w-3.5 h-3.5" />
          Add step
        </Button>
      )}
      <p className="text-[11px] text-muted-foreground">
        Placeholders: {"{first_name} {name} {company} {industry} {job_title} {company_size} {sender_name} {value_prop}"}
      </p>
    </div>
  );
}

function SequenceDialog({ open, onOpenChange, existing }: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  existing: Sequence | null;
}) {
  const qc = useQueryClient();
  const [name, setName] = useState(existing?.name ?? "");
  const [variant, setVariant] = useState(existing?.ab_variant ?? "");
  const [steps, setSteps] = useState<SequenceStep[]>(existing?.steps ?? [EMPTY_STEP(1)]);

  const { mutate: save, isPending } = useMutation({
    mutationFn: (): Promise<Sequence & { cloned_from_global?: boolean }> => {
      const payload = { name, ab_variant: variant || null, steps };
      return existing ? sequencesApi.update(existing.id, payload) : sequencesApi.create(payload);
    },
    onSuccess: (res: { cloned_from_global?: boolean }) => {
      qc.invalidateQueries({ queryKey: ["sequences"] });
      onOpenChange(false);
      toast.success(
        res.cloned_from_global
          ? "Shared template cloned into your workspace with your edits"
          : existing ? "Sequence updated" : "Sequence created"
      );
    },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, "Save failed — check that every step has a subject and body")),
  });

  const valid = name.trim() && steps.every((s) => s.subject_template.trim() && s.body_template.trim());

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{existing ? "Edit sequence" : "New sequence"}</DialogTitle>
          <DialogDescription>
            Multi-step cadence — the LLM personalises each step per lead before sending.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 mt-2">
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2 space-y-2">
              <Label>Name</Label>
              <Input placeholder="e.g. Enterprise 3-step" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>A/B variant</Label>
              <Input placeholder="A / B / C…" value={variant} onChange={(e) => setVariant(e.target.value)} maxLength={10} />
            </div>
          </div>
          <StepEditor steps={steps} onChange={setSteps} />
        </div>
        <DialogFooter>
          <Button variant="outline" type="button" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="gradient" disabled={!valid} loading={isPending} onClick={() => save()}>
            {existing ? "Save changes" : "Create sequence"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function Sequences() {
  const qc = useQueryClient();
  const { user } = useAuthStore();
  const isManager = user?.role === "admin" || user?.role === "manager";
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Sequence | null>(null);

  const { data, isLoading } = useQuery({ queryKey: ["sequences"], queryFn: sequencesApi.list });

  const { mutate: deactivate } = useMutation({
    mutationFn: sequencesApi.deactivate,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["sequences"] }); toast.success("Sequence deactivated"); },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, "Failed to deactivate")),
  });

  const openNew = () => { setEditing(null); setDialogOpen(true); };
  const openEdit = (seq: Sequence) => { setEditing(seq); setDialogOpen(true); };

  return (
    <div className="flex flex-col min-h-screen">
      <Header title="Sequences" subtitle="Author the cadences the agent personalises and sends" />
      <div className="flex-1 p-8 space-y-4 max-w-4xl animate-fade-in">
        <div className="flex items-center justify-between">
          <p className="text-sm text-muted-foreground">
            {data ? `${data.total} sequence(s) — the Thompson-sampling bandit routes traffic to the best performer` : ""}
          </p>
          {isManager && (
            <Button variant="gradient" size="sm" onClick={openNew} className="gap-1.5">
              <Plus className="w-3.5 h-3.5" />
              New sequence
            </Button>
          )}
        </div>

        {isLoading ? (
          <p className="text-sm text-muted-foreground py-8 text-center">Loading…</p>
        ) : (
          <div className="space-y-3">
            {data?.sequences.map((seq) => (
              <Card key={seq.id} className={!seq.is_active ? "opacity-60" : undefined}>
                <CardContent className="p-4">
                  <div className="flex items-center gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-medium truncate">{seq.name}</p>
                        {seq.ab_variant && <Badge variant="secondary" className="text-[10px]">variant {seq.ab_variant}</Badge>}
                        {seq.is_global && (
                          <Badge variant="outline" className="text-[10px] gap-1"><Globe2 className="w-2.5 h-2.5" />shared</Badge>
                        )}
                        {!seq.is_active && <Badge variant="warning" className="text-[10px]">inactive</Badge>}
                      </div>
                      <p className="text-xs text-muted-foreground mt-0.5 flex items-center gap-3">
                        <span>{seq.steps.length} steps</span>
                        <span className="flex items-center gap-1"><Mail className="w-3 h-3" />{seq.emails_sent} sent</span>
                        <span>{seq.conversions} conversions</span>
                      </p>
                    </div>
                    {isManager && (
                      <div className="flex items-center gap-1 shrink-0">
                        <Button variant="ghost" size="icon" onClick={() => openEdit(seq)} aria-label={`Edit ${seq.name}`}>
                          <PencilLine className="w-3.5 h-3.5" />
                        </Button>
                        {!seq.is_global && seq.is_active && (
                          <Button
                            variant="ghost"
                            size="icon"
                            className="text-red-400 hover:bg-red-500/10 hover:text-red-400"
                            onClick={() => { if (confirm(`Deactivate "${seq.name}"?`)) deactivate(seq.id); }}
                            aria-label={`Deactivate ${seq.name}`}
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </Button>
                        )}
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>

      {dialogOpen && (
        <SequenceDialog
          key={editing?.id ?? "new"}
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          existing={editing}
        />
      )}
    </div>
  );
}
