import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { GitBranch, CheckCircle2, XCircle, Clock, ChevronRight, Search } from "lucide-react";
import { leadsApi, pipelineApi } from "../lib/api";
import { Header } from "../components/layout/Header";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { cn } from "../lib/utils";
import type { Lead } from "../types";

// The fixed LangGraph node order for display
const PIPELINE_NODES = [
  { id: "orchestrate", label: "Orchestrate" },
  { id: "enrich", label: "Enrich" },
  { id: "score_intent", label: "Intent" },
  { id: "analyse", label: "Analyse" },
  { id: "validate", label: "Validate" },
  { id: "booking", label: "Booking" },
  { id: "outreach", label: "Outreach" },
  { id: "sync_crm", label: "CRM Sync" },
  { id: "human_handoff", label: "Handoff" },
];

function NodeBadge({ name, executed, error }: { name: string; executed: boolean; error?: boolean }) {
  return (
    <div
      className={cn(
        "flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border transition-all",
        executed && !error
          ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
          : executed && error
          ? "bg-red-500/10 border-red-500/30 text-red-400"
          : "bg-secondary/40 border-border text-muted-foreground/50"
      )}
    >
      {executed && !error ? (
        <CheckCircle2 className="w-3 h-3" />
      ) : executed && error ? (
        <XCircle className="w-3 h-3" />
      ) : (
        <Clock className="w-3 h-3" />
      )}
      {name}
    </div>
  );
}

function GraphDiagram({ executedNodes, errorNodes }: { executedNodes: string[]; errorNodes: string[] }) {
  const actionNodes = ["booking", "outreach", "sync_crm", "human_handoff"];
  const coreNodes = PIPELINE_NODES.filter((n) => !actionNodes.includes(n.id));
  const actionDisplayNodes = PIPELINE_NODES.filter((n) => actionNodes.includes(n.id));

  return (
    <div className="space-y-4">
      {/* Core chain */}
      <div className="flex flex-wrap items-center gap-1">
        {coreNodes.map((node, i) => (
          <div key={node.id} className="flex items-center gap-1">
            <NodeBadge
              name={node.label}
              executed={executedNodes.includes(node.id)}
              error={errorNodes.includes(node.id)}
            />
            {i < coreNodes.length - 1 && (
              <ChevronRight className="w-3 h-3 text-muted-foreground/40 shrink-0" />
            )}
          </div>
        ))}
        <ChevronRight className="w-3 h-3 text-muted-foreground/40 shrink-0" />
        <span className="text-xs text-muted-foreground italic">verdict routes to →</span>
      </div>
      {/* Action branches */}
      <div className="flex flex-wrap gap-2 pl-4 border-l-2 border-dashed border-border">
        {actionDisplayNodes.map((node) => (
          <NodeBadge
            key={node.id}
            name={node.label}
            executed={executedNodes.includes(node.id)}
            error={errorNodes.includes(node.id)}
          />
        ))}
      </div>
    </div>
  );
}

function TracePanel({ leadId }: { leadId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["pipeline-trace", leadId],
    queryFn: () => pipelineApi.trace(leadId),
    enabled: !!leadId,
  });

  if (isLoading) {
    return (
      <div className="space-y-2 p-4">
        {[...Array(5)].map((_, i) => <div key={i} className="skeleton h-10 rounded-lg" />)}
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="p-4 text-sm text-muted-foreground">
        No pipeline trace available for this lead.
      </div>
    );
  }

  const executedNodes = data.nodes_executed ?? data.agent_logs.map((l) => l.agent_name);
  const errorNodes = data.agent_logs.filter((l) => l.status === "failed").map((l) => l.agent_name);

  return (
    <div className="p-4 space-y-5">
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-sm font-medium">{data.lead_name}</span>
        <Badge variant={
          data.final_verdict === "Hot" ? "hot" :
          data.final_verdict === "Warm" ? "warm" :
          data.final_verdict === "Cold" ? "cold" : "secondary"
        }>
          {data.final_verdict ?? data.status}
        </Badge>
      </div>

      <div>
        <p className="text-xs text-muted-foreground mb-3 uppercase tracking-wider font-semibold">
          Graph Execution
        </p>
        <GraphDiagram executedNodes={executedNodes} errorNodes={errorNodes} />
      </div>

      {data.agent_logs.length > 0 && (
        <div>
          <p className="text-xs text-muted-foreground mb-2 uppercase tracking-wider font-semibold">
            Agent Log
          </p>
          <div className="space-y-1.5">
            {data.agent_logs.map((log) => (
              <div
                key={log.id}
                className="flex items-center gap-3 rounded-lg px-3 py-2 bg-secondary/30 text-xs"
              >
                {log.status === "success" ? (
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                ) : log.status === "failed" ? (
                  <XCircle className="w-3.5 h-3.5 text-red-400 shrink-0" />
                ) : (
                  <Clock className="w-3.5 h-3.5 text-yellow-400 shrink-0" />
                )}
                <span className="font-mono font-medium w-28 shrink-0">{log.agent_name}</span>
                <span className="text-muted-foreground flex-1 truncate">
                  {log.error_message ?? log.status}
                </span>
                {log.duration_ms != null && (
                  <span className="text-muted-foreground shrink-0">{log.duration_ms}ms</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function Pipeline() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const { data: leads, isLoading } = useQuery({
    queryKey: ["leads-pipeline"],
    queryFn: () => leadsApi.list(0, 200),
    refetchInterval: 15_000,
  });

  const filtered = (leads ?? []).filter(
    (l) =>
      l.name.toLowerCase().includes(search.toLowerCase()) ||
      l.company.toLowerCase().includes(search.toLowerCase())
  );

  // Aggregate node execution counts from status for overview (approximation)
  const statusCounts = (leads ?? []).reduce(
    (acc, l) => {
      acc[l.status] = (acc[l.status] ?? 0) + 1;
      return acc;
    },
    {} as Record<string, number>
  );

  const STAGE_MAP: Array<{ label: string; statuses: string[]; color: string }> = [
    { label: "Pending", statuses: ["pending"], color: "bg-yellow-400" },
    { label: "Processing", statuses: ["processing"], color: "bg-violet-400" },
    { label: "Complete", statuses: ["complete"], color: "bg-emerald-400" },
    { label: "Failed", statuses: ["failed"], color: "bg-red-400" },
  ];

  return (
    <div className="flex flex-col min-h-screen">
      <Header
        title="Pipeline"
        subtitle="LangGraph multi-agent execution traces"
      />

      <div className="flex-1 p-8 space-y-6 animate-fade-in">
        {/* Stage overview */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {STAGE_MAP.map(({ label, statuses, color }) => {
            const count = statuses.reduce((n, s) => n + (statusCounts[s] ?? 0), 0);
            return (
              <Card key={label} className="relative overflow-hidden">
                <div className={cn("absolute left-0 top-0 bottom-0 w-1", color)} />
                <CardContent className="pl-5 pt-4 pb-4">
                  <p className="text-xs text-muted-foreground">{label}</p>
                  <p className="text-2xl font-bold mt-0.5">{count}</p>
                </CardContent>
              </Card>
            );
          })}
        </div>

        {/* Graph topology legend */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center gap-2">
              <GitBranch className="w-4 h-4 text-violet-400" />
              <CardTitle className="text-sm">LangGraph State Machine</CardTitle>
            </div>
            <CardDescription>
              Conditional routing: validate → Hot→booking, Warm→outreach, Cold→sync_crm
            </CardDescription>
          </CardHeader>
          <CardContent>
            <GraphDiagram executedNodes={[]} errorNodes={[]} />
          </CardContent>
        </Card>

        {/* Lead list + trace panel */}
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
          {/* Lead list */}
          <Card className="lg:col-span-2">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Leads</CardTitle>
              <div className="relative mt-1">
                <Search className="absolute left-2.5 top-2.5 w-3.5 h-3.5 text-muted-foreground" />
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search..."
                  className="w-full pl-8 pr-3 py-1.5 text-xs rounded-md bg-secondary border border-border focus:outline-none focus:ring-1 focus:ring-primary/50"
                />
              </div>
            </CardHeader>
            <CardContent className="p-0 max-h-[480px] overflow-y-auto">
              {isLoading ? (
                <div className="p-4 space-y-2">
                  {[...Array(6)].map((_, i) => <div key={i} className="skeleton h-12 rounded" />)}
                </div>
              ) : filtered.length === 0 ? (
                <div className="p-6 text-center text-sm text-muted-foreground">No leads found</div>
              ) : (
                <div className="divide-y divide-border">
                  {filtered.map((lead: Lead) => (
                    <button
                      key={lead.id}
                      onClick={() => setSelectedId(lead.id)}
                      className={cn(
                        "w-full text-left flex items-center gap-3 px-4 py-3 hover:bg-secondary/40 transition-colors",
                        selectedId === lead.id && "bg-primary/10"
                      )}
                    >
                      <div className="w-7 h-7 rounded-full bg-gradient-to-br from-violet-600 to-indigo-600 flex items-center justify-center text-white text-[10px] font-semibold shrink-0">
                        {lead.name.slice(0, 2).toUpperCase()}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium truncate">{lead.name}</p>
                        <p className="text-[10px] text-muted-foreground truncate">{lead.company}</p>
                      </div>
                      <Badge
                        variant={
                          lead.final_verdict === "Hot" ? "hot" :
                          lead.final_verdict === "Warm" ? "warm" :
                          lead.final_verdict === "Cold" ? "cold" : "secondary"
                        }
                        className="text-[10px] shrink-0"
                      >
                        {lead.final_verdict ?? lead.status}
                      </Badge>
                    </button>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Trace panel */}
          <Card className="lg:col-span-3">
            <CardHeader className="pb-0">
              <CardTitle className="text-sm">Execution Trace</CardTitle>
              <CardDescription>
                {selectedId ? "Agent-by-agent breakdown for selected lead" : "Select a lead to view its pipeline trace"}
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              {selectedId ? (
                <TracePanel leadId={selectedId} />
              ) : (
                <div className="p-12 text-center text-sm text-muted-foreground">
                  <GitBranch className="w-8 h-8 mx-auto mb-3 text-muted-foreground/30" />
                  Click any lead on the left to inspect its agent execution trace.
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
