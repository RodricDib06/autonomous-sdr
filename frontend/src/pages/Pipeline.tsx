import { useState, useEffect, useRef, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  GitBranch, CheckCircle2, XCircle, Clock, ChevronRight,
  Search, Play, Loader2, Wifi, WifiOff, FlaskConical,
} from "lucide-react";
import { leadsApi, pipelineApi } from "../lib/api";
import { Header } from "../components/layout/Header";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { cn } from "../lib/utils";
import type { Lead } from "../types";

const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

// All pipeline nodes in execution order — now includes "research"
const PIPELINE_NODES = [
  { id: "orchestrate",   label: "Orchestrate" },
  { id: "enrich",        label: "Enrich" },
  { id: "research",      label: "Research" },   // ReAct tool-calling agent
  { id: "score_intent",  label: "Intent" },
  { id: "analyse",       label: "Analyse" },
  { id: "validate",      label: "Validate" },
  { id: "booking",       label: "Booking" },
  { id: "outreach",      label: "Outreach" },
  { id: "sync_crm",      label: "CRM Sync" },
  { id: "human_handoff", label: "Handoff" },
];

// ── Types ──────────────────────────────────────────────────────────────────────

interface StreamEvent {
  node: string;
  status: "running" | "complete" | "error" | "connected" | "timeout";
  duration_ms?: number;
  verdict?: string;
  score?: number;
  iterations?: number;
  summary?: string;
  error?: string;
  [key: string]: unknown;
}

interface NodeLiveState {
  status: "idle" | "running" | "complete" | "error";
  duration_ms?: number;
  meta?: Record<string, unknown>;
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function NodeBadge({
  name, state,
}: {
  name: string;
  state: NodeLiveState;
}) {
  const isRunning = state.status === "running";
  const isDone    = state.status === "complete";
  const isError   = state.status === "error";

  return (
    <div
      className={cn(
        "flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border transition-all duration-300",
        isDone  && "bg-emerald-500/10 border-emerald-500/30 text-emerald-400",
        isError && "bg-red-500/10 border-red-500/30 text-red-400",
        isRunning && "bg-violet-500/10 border-violet-500/40 text-violet-300 animate-pulse",
        state.status === "idle" && "bg-secondary/40 border-border text-muted-foreground/50",
      )}
    >
      {isRunning ? (
        <Loader2 className="w-3 h-3 animate-spin" />
      ) : isDone ? (
        <CheckCircle2 className="w-3 h-3" />
      ) : isError ? (
        <XCircle className="w-3 h-3" />
      ) : (
        <Clock className="w-3 h-3" />
      )}
      {name}
      {isDone && state.duration_ms != null && (
        <span className="opacity-60 text-[10px]">{state.duration_ms}ms</span>
      )}
    </div>
  );
}

function GraphDiagram({
  nodeStates,
}: {
  nodeStates: Record<string, NodeLiveState>;
}) {
  const actionNodes = ["booking", "outreach", "sync_crm", "human_handoff"];
  const coreNodes   = PIPELINE_NODES.filter((n) => !actionNodes.includes(n.id));
  const actionDisplayNodes = PIPELINE_NODES.filter((n) => actionNodes.includes(n.id));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-1">
        {coreNodes.map((node, i) => (
          <div key={node.id} className="flex items-center gap-1">
            <NodeBadge
              name={node.label}
              state={nodeStates[node.id] ?? { status: "idle" }}
            />
            {i < coreNodes.length - 1 && (
              <ChevronRight className="w-3 h-3 text-muted-foreground/40 shrink-0" />
            )}
          </div>
        ))}
        <ChevronRight className="w-3 h-3 text-muted-foreground/40 shrink-0" />
        <span className="text-xs text-muted-foreground italic">verdict routes to →</span>
      </div>
      <div className="flex flex-wrap gap-2 pl-4 border-l-2 border-dashed border-border">
        {actionDisplayNodes.map((node) => (
          <NodeBadge
            key={node.id}
            name={node.label}
            state={nodeStates[node.id] ?? { status: "idle" }}
          />
        ))}
      </div>
    </div>
  );
}

// ── Live stream panel ──────────────────────────────────────────────────────────

function LiveStreamPanel({ leadId, onDone }: { leadId: string; onDone: (verdict: string) => void }) {
  const [connected, setConnected] = useState(false);
  const [done, setDone] = useState(false);
  const [verdict, setVerdict] = useState<string | null>(null);
  const [nodeStates, setNodeStates] = useState<Record<string, NodeLiveState>>({});
  const [eventLog, setEventLog] = useState<StreamEvent[]>([]);
  const esRef = useRef<EventSource | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    // EventSource doesn't support headers — pass token as query param for streaming
    const url = `${BASE_URL}/leads/${leadId}/pipeline/stream?token=${token ?? ""}`;
    const es = new EventSource(url);
    esRef.current = es;

    es.onopen = () => setConnected(true);

    es.onmessage = (e) => {
      let event: StreamEvent;
      try { event = JSON.parse(e.data); } catch { return; }

      setEventLog((prev) => [...prev, event]);

      if (event.node === "pipeline" && event.status === "complete") {
        setDone(true);
        setVerdict(event.verdict ?? null);
        onDone(event.verdict ?? "unknown");
        es.close();
        return;
      }

      if (event.node === "stream") return;  // internal heartbeat

      setNodeStates((prev) => {
        if (event.status === "running") {
          return { ...prev, [event.node]: { status: "running" } };
        }
        if (event.status === "complete") {
          return { ...prev, [event.node]: { status: "complete", duration_ms: event.duration_ms, meta: event as Record<string, unknown> } };
        }
        if (event.status === "error") {
          return { ...prev, [event.node]: { status: "error" } };
        }
        return prev;
      });
    };

    es.onerror = () => {
      setConnected(false);
      es.close();
    };

    return () => es.close();
  }, [leadId, onDone]);

  // Auto-scroll event log
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [eventLog]);

  return (
    <div className="p-4 space-y-4">
      {/* Connection status */}
      <div className="flex items-center gap-2 text-xs">
        {done ? (
          <>
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
            <span className="text-emerald-400 font-medium">Pipeline complete</span>
            {verdict && (
              <Badge variant={verdict === "Hot" ? "hot" : verdict === "Warm" ? "warm" : "cold"}>
                {verdict}
              </Badge>
            )}
          </>
        ) : connected ? (
          <>
            <Wifi className="w-3.5 h-3.5 text-violet-400 animate-pulse" />
            <span className="text-violet-400">Live — streaming node events</span>
          </>
        ) : (
          <>
            <WifiOff className="w-3.5 h-3.5 text-muted-foreground" />
            <span className="text-muted-foreground">Connecting…</span>
          </>
        )}
      </div>

      {/* Live graph diagram */}
      <div>
        <p className="text-xs text-muted-foreground mb-3 uppercase tracking-wider font-semibold">
          Live Execution
        </p>
        <GraphDiagram nodeStates={nodeStates} />
      </div>

      {/* Event log */}
      {eventLog.length > 0 && (
        <div>
          <p className="text-xs text-muted-foreground mb-2 uppercase tracking-wider font-semibold">
            Event Stream
          </p>
          <div ref={logRef} className="space-y-1 max-h-52 overflow-y-auto">
            {eventLog
              .filter((e) => e.node !== "stream")
              .map((event, i) => (
                <div
                  key={i}
                  className="flex items-start gap-2 rounded px-2.5 py-1.5 bg-secondary/30 text-xs font-mono"
                >
                  <span
                    className={cn(
                      "shrink-0 w-2 h-2 rounded-full mt-0.5",
                      event.status === "running"  && "bg-violet-400 animate-pulse",
                      event.status === "complete" && "bg-emerald-400",
                      event.status === "error"    && "bg-red-400",
                    )}
                  />
                  <span className="text-muted-foreground w-24 shrink-0">{event.node}</span>
                  <span className={cn(
                    "flex-1",
                    event.status === "complete" && "text-emerald-400",
                    event.status === "error"    && "text-red-400",
                    event.status === "running"  && "text-violet-300",
                  )}>
                    {event.status}
                    {event.status === "complete" && event.duration_ms != null && ` · ${event.duration_ms}ms`}
                    {event.status === "complete" && event.verdict && ` · verdict=${event.verdict}`}
                    {event.status === "complete" && event.score != null && ` · score=${event.score}`}
                    {event.status === "complete" && event.iterations != null && ` · ${event.iterations} tool call(s)`}
                    {event.status === "error" && event.error && ` · ${event.error}`}
                  </span>
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Static trace panel (post-run) ─────────────────────────────────────────────

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
  const nodeStates: Record<string, NodeLiveState> = {};
  for (const n of executedNodes) nodeStates[n] = { status: "complete" };
  for (const n of errorNodes) nodeStates[n] = { status: "error" };

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
        <GraphDiagram nodeStates={nodeStates} />
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

// ── Main page ──────────────────────────────────────────────────────────────────

export default function Pipeline() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [streamingId, setStreamingId] = useState<string | null>(null);

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

  const statusCounts = (leads ?? []).reduce(
    (acc, l) => { acc[l.status] = (acc[l.status] ?? 0) + 1; return acc; },
    {} as Record<string, number>
  );

  const STAGE_MAP = [
    { label: "Pending",    statuses: ["pending"],    color: "bg-yellow-400" },
    { label: "Processing", statuses: ["processing"], color: "bg-violet-400" },
    { label: "Complete",   statuses: ["complete"],   color: "bg-emerald-400" },
    { label: "Failed",     statuses: ["failed"],     color: "bg-red-400" },
  ];

  const handleRunLive = useCallback(async (leadId: string) => {
    setSelectedId(leadId);
    setStreamingId(leadId);
    // Re-queue the lead for processing
    try {
      await leadsApi.reprocessFailed();
    } catch {
      // Lead may already be pending — stream will still show existing run
    }
  }, []);

  const handleStreamDone = useCallback((_verdict: string) => {
    setTimeout(() => {
      queryClient.invalidateQueries({ queryKey: ["leads-pipeline"] });
      queryClient.invalidateQueries({ queryKey: ["pipeline-trace", streamingId] });
    }, 1000);
  }, [queryClient, streamingId]);

  const showStream = streamingId === selectedId && streamingId !== null;

  return (
    <div className="flex flex-col min-h-screen">
      <Header
        title="Pipeline"
        subtitle="LangGraph multi-agent execution — live streaming + historical traces"
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
              <CardTitle className="text-sm">LangGraph State Machine — 10 nodes</CardTitle>
            </div>
            <CardDescription>
              orchestrate → enrich → <span className="text-violet-300 font-medium">research (ReAct)</span> → score_intent → analyse → validate → Hot/Warm/Cold routing
            </CardDescription>
          </CardHeader>
          <CardContent>
            <GraphDiagram nodeStates={{}} />
          </CardContent>
        </Card>

        {/* Lead list + trace/stream panel */}
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
            <CardContent className="p-0 max-h-[520px] overflow-y-auto">
              {isLoading ? (
                <div className="p-4 space-y-2">
                  {[...Array(6)].map((_, i) => <div key={i} className="skeleton h-12 rounded" />)}
                </div>
              ) : filtered.length === 0 ? (
                <div className="p-6 text-center text-sm text-muted-foreground">No leads found</div>
              ) : (
                <div className="divide-y divide-border">
                  {filtered.map((lead: Lead) => (
                    <div
                      key={lead.id}
                      className={cn(
                        "flex items-center gap-2 px-3 py-2.5 hover:bg-secondary/40 transition-colors cursor-pointer",
                        selectedId === lead.id && "bg-primary/10"
                      )}
                      onClick={() => { setSelectedId(lead.id); setStreamingId(null); }}
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
                          lead.final_verdict === "Hot"  ? "hot"  :
                          lead.final_verdict === "Warm" ? "warm" :
                          lead.final_verdict === "Cold" ? "cold" : "secondary"
                        }
                        className="text-[10px] shrink-0"
                      >
                        {lead.final_verdict ?? lead.status}
                      </Badge>
                      {/* Live run button */}
                      <button
                        title="Run pipeline live"
                        onClick={(e) => { e.stopPropagation(); handleRunLive(lead.id); }}
                        className={cn(
                          "shrink-0 p-1 rounded hover:bg-violet-500/20 transition-colors",
                          streamingId === lead.id ? "text-violet-400" : "text-muted-foreground/40 hover:text-violet-400"
                        )}
                      >
                        {streamingId === lead.id ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <Play className="w-3.5 h-3.5" />
                        )}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Trace / stream panel */}
          <Card className="lg:col-span-3">
            <CardHeader className="pb-0">
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-sm">
                    {showStream ? "Live Pipeline Stream" : "Execution Trace"}
                  </CardTitle>
                  <CardDescription>
                    {showStream
                      ? "Watching node events in real time via SSE"
                      : selectedId
                      ? "Agent-by-agent breakdown — click ▶ to watch a live run"
                      : "Select a lead to view its pipeline trace"}
                  </CardDescription>
                </div>
                {selectedId && !showStream && (
                  <button
                    onClick={() => handleRunLive(selectedId)}
                    className="flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-md bg-violet-500/10 border border-violet-500/30 text-violet-300 hover:bg-violet-500/20 transition-colors"
                  >
                    <Play className="w-3 h-3" /> Run Live
                  </button>
                )}
              </div>
            </CardHeader>
            <CardContent className="p-0">
              {showStream ? (
                <LiveStreamPanel
                  leadId={streamingId!}
                  onDone={handleStreamDone}
                />
              ) : selectedId ? (
                <TracePanel leadId={selectedId} />
              ) : (
                <div className="p-12 text-center text-sm text-muted-foreground">
                  <GitBranch className="w-8 h-8 mx-auto mb-3 text-muted-foreground/30" />
                  <p>Click any lead to view its trace</p>
                  <p className="text-xs mt-1 text-muted-foreground/60">
                    or click <span className="text-violet-400">▶</span> to watch the pipeline run live
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Research agent callout */}
        <Card className="border-violet-500/20 bg-violet-500/5">
          <CardContent className="py-3 px-4">
            <div className="flex items-start gap-3">
              <FlaskConical className="w-4 h-4 text-violet-400 shrink-0 mt-0.5" />
              <div className="text-xs text-muted-foreground space-y-0.5">
                <p className="text-violet-300 font-medium">ReAct Research Agent</p>
                <p>
                  Before BANT analysis, the <strong className="text-foreground">research</strong> node
                  autonomously decides which tools to call — <code>search_web</code>,{" "}
                  <code>check_funding</code>, or <code>verify_icp</code> — based on the enriched lead
                  context. Tool results are injected into the analysis prompt, giving the LLM real
                  web context instead of just structured fields.
                  {" "}
                  {import.meta.env.VITE_API_URL?.includes("localhost")
                    ? "Set TAVILY_API_KEY for live web search; DuckDuckGo is the free fallback."
                    : "Powered by Tavily search."}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
