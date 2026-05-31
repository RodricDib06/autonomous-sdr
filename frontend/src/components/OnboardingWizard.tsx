/**
 * OnboardingWizard
 *
 * Shown automatically when total_leads == 0 and the wizard has not been
 * dismissed. Stored in localStorage so it never reappears after dismiss.
 *
 * Steps:
 *   1. Welcome — what AutonomousSDR does
 *   2. Set ICP — link to /icp so they configure criteria
 *   3. Load demo data — one-click seed via POST /seed/demo
 *   4. Done — close and start exploring
 */

import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { Zap, Target, Database, CheckCircle2, ChevronRight, X } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { leadsApi, seedApi } from "../lib/api";
import { Button } from "./ui/button";
import { cn } from "../lib/utils";

const DISMISSED_KEY = "asdr_wizard_dismissed";

const STEPS = [
  {
    id: "welcome",
    icon: Zap,
    title: "Welcome to AutonomousSDR",
    color: "text-violet-400",
    bg: "bg-violet-500/10 border-violet-500/20",
  },
  {
    id: "icp",
    icon: Target,
    title: "Define your ICP",
    color: "text-emerald-400",
    bg: "bg-emerald-500/10 border-emerald-500/20",
  },
  {
    id: "seed",
    icon: Database,
    title: "Load demo data",
    color: "text-orange-400",
    bg: "bg-orange-500/10 border-orange-500/20",
  },
  {
    id: "done",
    icon: CheckCircle2,
    title: "You're ready",
    color: "text-emerald-400",
    bg: "bg-emerald-500/10 border-emerald-500/20",
  },
] as const;

type StepId = typeof STEPS[number]["id"];

export function OnboardingWizard() {
  const navigate = useNavigate();
  const [step, setStep] = useState<StepId>("welcome");
  const [seeded, setSeeded] = useState(false);
  const [dismissed, setDismissed] = useState(
    () => localStorage.getItem(DISMISSED_KEY) === "1"
  );

  const { data: stats } = useQuery({
    queryKey: ["stats"],
    queryFn: leadsApi.stats,
    staleTime: 30_000,
  });

  const { mutate: seed, isPending: seeding } = useMutation({
    mutationFn: seedApi.demo,
    onSuccess: (d) => {
      if (d.status === "already_seeded") {
        toast("Demo data already loaded — you're good to go!");
      } else {
        toast.success("Demo data loading in the background — refresh in ~5 seconds.");
      }
      setSeeded(true);
    },
    onError: () => toast.error("Seeding failed — run `python scripts/seed_demo_data.py` manually."),
  });

  const dismiss = () => {
    localStorage.setItem(DISMISSED_KEY, "1");
    setDismissed(true);
  };

  // Only show when: not dismissed AND total_leads is 0
  if (dismissed) return null;
  if (stats === undefined) return null; // loading
  if (stats.total_leads > 0) return null; // already has data

  const stepIdx = STEPS.findIndex((s) => s.id === step);
  const currentStep = STEPS[stepIdx];
  const Icon = currentStep.icon;

  const next = () => {
    const nextStep = STEPS[stepIdx + 1];
    if (nextStep) setStep(nextStep.id);
    else dismiss();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg bg-card border border-border rounded-2xl shadow-2xl overflow-hidden animate-fade-in">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-md bg-gradient-to-br from-violet-600 to-indigo-600 flex items-center justify-center">
              <Zap className="w-3.5 h-3.5 text-white" />
            </div>
            <span className="font-semibold text-sm">Setup wizard</span>
          </div>
          <button onClick={dismiss} className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Step indicator */}
        <div className="flex px-6 pt-5 gap-2">
          {STEPS.map((s, i) => (
            <div
              key={s.id}
              className={cn(
                "flex-1 h-1.5 rounded-full transition-all",
                i <= stepIdx ? "bg-violet-500" : "bg-secondary"
              )}
            />
          ))}
        </div>

        {/* Step content */}
        <div className="px-6 py-6 space-y-4">
          <div className={cn("flex items-center gap-3 p-4 rounded-xl border", currentStep.bg)}>
            <Icon className={cn("w-6 h-6 shrink-0", currentStep.color)} />
            <h2 className="font-semibold text-lg">{currentStep.title}</h2>
          </div>

          {step === "welcome" && (
            <div className="space-y-3 text-sm text-muted-foreground">
              <p>
                <span className="text-foreground font-medium">AutonomousSDR</span> is a multi-agent AI lead qualification platform.
                It automatically enriches, scores, and qualifies leads using a LangGraph pipeline — so your team spends time only on deals that are genuinely ready to close.
              </p>
              <ul className="space-y-1.5 pl-4 list-disc">
                <li>BANT scoring with self-optimizing weights</li>
                <li>ML-predicted close probability per lead</li>
                <li>Real-time engagement decay alerts</li>
                <li>pgvector semantic search over conversations</li>
              </ul>
              <p className="text-xs">This wizard takes 2 minutes to get you started.</p>
            </div>
          )}

          {step === "icp" && (
            <div className="space-y-3 text-sm text-muted-foreground">
              <p>
                Define your <span className="text-foreground font-medium">Ideal Customer Profile</span> — target industries, seniority levels, and company size. The pipeline will evaluate every lead against these criteria automatically.
              </p>
              <p>You can always update it later from the <strong>ICP Builder</strong> in the sidebar.</p>
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5 w-full"
                onClick={() => { navigate("/icp"); dismiss(); }}
              >
                <Target className="w-3.5 h-3.5" />
                Open ICP Builder
                <ChevronRight className="w-3.5 h-3.5 ml-auto" />
              </Button>
              <p className="text-[11px]">Or skip and set it up later — you can continue without an ICP configured.</p>
            </div>
          )}

          {step === "seed" && (
            <div className="space-y-3 text-sm text-muted-foreground">
              <p>
                Load <span className="text-foreground font-medium">~150 realistic demo leads</span> with enrichments, BANT scores, outreach history, and 6 optimization runs so every chart and feature is immediately populated.
              </p>
              <p className="text-xs">Runs in the background — the dashboard will update in ~5 seconds.</p>
              {seeded ? (
                <div className="flex items-center gap-2 text-emerald-400 text-sm font-medium">
                  <CheckCircle2 className="w-4 h-4" />
                  Demo data is loading — refresh the Dashboard in a moment.
                </div>
              ) : (
                <Button
                  variant="gradient"
                  size="sm"
                  className="w-full gap-1.5"
                  onClick={() => seed()}
                  loading={seeding}
                >
                  <Database className="w-3.5 h-3.5" />
                  Load demo data
                </Button>
              )}
            </div>
          )}

          {step === "done" && (
            <div className="space-y-3 text-sm text-muted-foreground">
              <p>
                You're all set! Here are a few things to try first:
              </p>
              <ul className="space-y-1.5 pl-4 list-disc">
                <li>Open a lead → check the <strong>BANT breakdown</strong> and <strong>ML close probability</strong></li>
                <li>Visit <strong>Analytics</strong> → see the Market Intelligence segments</li>
                <li>Press <kbd className="px-1 py-0.5 rounded border border-border font-mono text-[10px]">?</kbd> on the Leads page for keyboard shortcuts</li>
                <li>Visit <strong>ICP Builder</strong> → configure your target customer</li>
              </ul>
            </div>
          )}
        </div>

        {/* Footer actions */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-border bg-secondary/20">
          <button
            onClick={dismiss}
            className="text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            Skip wizard
          </button>
          <div className="flex items-center gap-2">
            {stepIdx > 0 && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setStep(STEPS[stepIdx - 1].id)}
              >
                Back
              </Button>
            )}
            <Button variant="gradient" size="sm" onClick={next} className="gap-1.5">
              {step === "done" ? "Start exploring" : "Continue"}
              <ChevronRight className="w-3.5 h-3.5" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
