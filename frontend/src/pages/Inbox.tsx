import { useState, useRef, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  MessageSquare, AlertTriangle, CheckCircle2, Send, Bot, User, RefreshCw,
  ChevronDown, Inbox as InboxIcon,
} from "lucide-react";
import { toast } from "sonner";
import { inboxApi } from "../lib/api";
import type { InboxConversation, ConversationMessage } from "../types";
import { Header } from "../components/layout/Header";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Card } from "../components/ui/card";
import { cn } from "../lib/utils";

// ── Sentiment helpers ────────────────────────────────────────────────────────

const SENTIMENT_META: Record<string, { label: string; class: string }> = {
  positive:  { label: "Positive",  class: "text-emerald-400 bg-emerald-500/10 border-emerald-500/30" },
  neutral:   { label: "Neutral",   class: "text-slate-400 bg-slate-500/10 border-slate-500/20" },
  curious:   { label: "Curious",   class: "text-blue-400 bg-blue-500/10 border-blue-500/30" },
  skeptical: { label: "Skeptical", class: "text-yellow-400 bg-yellow-500/10 border-yellow-500/30" },
  frustrated:{ label: "Frustrated",class: "text-orange-400 bg-orange-500/10 border-orange-500/30" },
  angry:     { label: "Angry",     class: "text-red-400 bg-red-500/10 border-red-500/30" },
};

const OBJECTION_LABELS: Record<string, string> = {
  price_objection:      "Price",
  timing_objection:     "Timing",
  authority_objection:  "Authority",
  need_objection:       "No Need",
  trust_objection:      "Trust",
  competition_objection:"Competition",
  feature_objection:    "Feature Gap",
  general_objection:    "General",
};

const CLASSIFICATION_META: Record<string, { label: string; class: string }> = {
  interested:   { label: "Interested",    class: "text-emerald-400 bg-emerald-500/10 border-emerald-900/50" },
  objection:    { label: "Objection",     class: "text-yellow-400 bg-yellow-500/10 border-yellow-900/50" },
  referral:     { label: "Referral",      class: "text-violet-400 bg-violet-500/10 border-violet-900/50" },
  wrong_person: { label: "Wrong person",  class: "text-orange-400 bg-orange-500/10 border-orange-900/50" },
  not_now:      { label: "Not now",       class: "text-blue-400 bg-blue-500/10 border-blue-900/50" },
  auto_reply:   { label: "Auto-reply",    class: "text-muted-foreground bg-secondary/40 border-border" },
};

function ClassificationBadge({ classification }: { classification: InboxConversation["classification"] }) {
  if (!classification) return null;
  const meta = CLASSIFICATION_META[classification.category];
  if (!meta) return null;
  const label = classification.category === "objection" && classification.subtype
    ? `Objection: ${classification.subtype.replace("_", " ")}`
    : meta.label;
  return (
    <span
      title={`Classified by ${classification.method} (confidence ${Math.round(classification.confidence * 100)}%)`}
      className={cn("inline-flex items-center px-2 py-0.5 rounded-full border text-[10px] font-semibold uppercase tracking-wide", meta.class)}
    >
      {label}
    </span>
  );
}

function SentimentBadge({ sentiment }: { sentiment: string | null }) {
  if (!sentiment) return null;
  const meta = SENTIMENT_META[sentiment] ?? { label: sentiment, class: "text-muted-foreground bg-secondary/40 border-border" };
  return (
    <span className={cn("inline-flex items-center px-2 py-0.5 rounded-full border text-[10px] font-semibold uppercase tracking-wide", meta.class)}>
      {meta.label}
    </span>
  );
}

function formatTime(ts: string | null) {
  if (!ts) return "";
  const d = new Date(ts);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffH = diffMs / 3_600_000;
  if (diffH < 24) return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

// ── Message bubble ────────────────────────────────────────────────────────────

function MessageBubble({ msg }: { msg: ConversationMessage }) {
  const isAgent = msg.role === "assistant" || msg.role === "agent";

  return (
    <div className={cn("flex gap-2.5 max-w-[85%]", isAgent ? "self-start" : "self-end flex-row-reverse")}>
      <div className={cn(
        "w-7 h-7 rounded-full flex items-center justify-center shrink-0 mt-0.5",
        isAgent ? "bg-violet-500/20" : "bg-blue-500/20",
      )}>
        {isAgent ? (
          <Bot className="w-3.5 h-3.5 text-violet-400" />
        ) : (
          <User className="w-3.5 h-3.5 text-blue-400" />
        )}
      </div>
      <div className={cn(
        "flex flex-col gap-1",
        isAgent ? "items-start" : "items-end",
      )}>
        <div className={cn(
          "rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed",
          isAgent
            ? "bg-secondary/60 text-foreground rounded-tl-sm"
            : "bg-blue-500/15 border border-blue-500/20 text-foreground rounded-tr-sm",
        )}>
          {msg.content}
        </div>
        {msg.timestamp && (
          <p className="text-[10px] text-muted-foreground/60 px-1">
            {formatTime(msg.timestamp)}
          </p>
        )}
      </div>
    </div>
  );
}

// ── Conversation list item ────────────────────────────────────────────────────

function ConvItem({
  conv,
  selected,
  onClick,
}: {
  conv: InboxConversation;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full text-left p-3.5 border-b border-border transition-colors",
        selected ? "bg-primary/10 border-l-2 border-l-primary" : "hover:bg-secondary/40",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <p className="text-sm font-medium truncate">{conv.lead_name}</p>
            {conv.needs_human && (
              <AlertTriangle className="w-3 h-3 text-orange-400 shrink-0" />
            )}
          </div>
          <p className="text-xs text-muted-foreground truncate">{conv.company}</p>
        </div>
        <div className="shrink-0 flex flex-col items-end gap-1">
          <p className="text-[10px] text-muted-foreground">{formatTime(conv.updated_at)}</p>
          <span className="text-[10px] text-muted-foreground">{conv.channel}</span>
        </div>
      </div>
      {conv.summary && (
        <p className="text-xs text-muted-foreground/70 mt-1 line-clamp-1">{conv.summary}</p>
      )}
      <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
        <ClassificationBadge classification={conv.classification} />
        {conv.sentiment && <SentimentBadge sentiment={conv.sentiment} />}
        <span className="text-[10px] text-muted-foreground">
          {conv.message_count} msg{conv.message_count !== 1 ? "s" : ""}
        </span>
      </div>
    </button>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Inbox() {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<InboxConversation | null>(null);
  const [filterReview, setFilterReview] = useState(false);
  const [reply, setReply] = useState("");
  const [simReply, setSimReply] = useState("");
  const [showSimInput, setShowSimInput] = useState(false);
  const threadEndRef = useRef<HTMLDivElement>(null);

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["inbox", filterReview],
    queryFn: () => inboxApi.list(filterReview ? { needs_human: true } : undefined),
    staleTime: 15_000,
    refetchInterval: 30_000,
  });

  // Auto-select first on load
  useEffect(() => {
    if (!selected && data?.conversations?.length) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelected(data.conversations[0]);
    }
  }, [data, selected]);

  // Scroll thread to bottom when conversation changes
  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [selected?.id, selected?.messages.length]);

  // Keep selected conv fresh from query data
  useEffect(() => {
    if (selected && data?.conversations) {
      const fresh = data.conversations.find((c) => c.id === selected.id);
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (fresh) setSelected(fresh);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const { mutate: resolveMut, isPending: resolving } = useMutation({
    mutationFn: (convId: string) => inboxApi.resolve(convId),
    onSuccess: () => {
      toast.success("Conversation resolved — human review cleared");
      qc.invalidateQueries({ queryKey: ["inbox"] });
    },
    onError: () => toast.error("Failed to resolve conversation"),
  });

  const { mutate: sendReplyMut, isPending: sendingReply } = useMutation({
    mutationFn: ({ leadId, message }: { leadId: string; message: string }) =>
      inboxApi.reply(leadId, message),
    onSuccess: (data) => {
      toast.success("Reply sent", {
        description: data.needs_human ? "AI flagged for human review" : "Delivered via " + data.delivery,
      });
      setReply("");
      qc.invalidateQueries({ queryKey: ["inbox"] });
    },
    onError: () => toast.error("Failed to send reply"),
  });

  const { mutate: simReplyMut, isPending: simulating } = useMutation({
    mutationFn: ({ leadId, message }: { leadId: string; message: string }) =>
      inboxApi.simulateReply(leadId, message),
    onSuccess: (data) => {
      toast.info("Lead reply simulated", {
        description: data.objection_type
          ? `Objection: ${OBJECTION_LABELS[data.objection_type] ?? data.objection_type}`
          : "No objection detected",
      });
      setSimReply("");
      setShowSimInput(false);
      qc.invalidateQueries({ queryKey: ["inbox"] });
    },
    onError: () => toast.error("Simulation failed"),
  });

  const convs = data?.conversations ?? [];

  return (
    <div className="flex flex-col h-full">
      <Header
        title="Inbox"
        subtitle="AI-managed reply threads — flagged when human judgment needed"
        actions={
          <div className="flex items-center gap-2">
            {data?.needs_review != null && data.needs_review > 0 && (
              <Badge variant="destructive" className="text-[11px]">
                {data.needs_review} need review
              </Badge>
            )}
            <Button
              size="sm"
              variant="outline"
              onClick={() => refetch()}
              disabled={isFetching}
              className="gap-2"
            >
              <RefreshCw className={cn("w-3.5 h-3.5", isFetching && "animate-spin")} />
              Refresh
            </Button>
          </div>
        }
      />

      <div className="flex flex-1 overflow-hidden">

        {/* ── Left panel: conversation list ── */}
        <div className="w-80 shrink-0 border-r border-border flex flex-col">
          {/* Filter tabs */}
          <div className="flex border-b border-border">
            <button
              onClick={() => setFilterReview(false)}
              className={cn(
                "flex-1 py-2.5 text-xs font-medium transition-colors",
                !filterReview ? "text-primary border-b-2 border-primary bg-primary/5" : "text-muted-foreground hover:text-foreground",
              )}
            >
              All ({data?.count ?? 0})
            </button>
            <button
              onClick={() => setFilterReview(true)}
              className={cn(
                "flex-1 py-2.5 text-xs font-medium transition-colors flex items-center justify-center gap-1.5",
                filterReview ? "text-orange-400 border-b-2 border-orange-400 bg-orange-500/5" : "text-muted-foreground hover:text-foreground",
              )}
            >
              <AlertTriangle className="w-3 h-3" />
              Needs Review ({data?.needs_review ?? 0})
            </button>
          </div>

          {/* List */}
          <div className="flex-1 overflow-y-auto">
            {isLoading ? (
              <div className="p-4 space-y-3">
                {[...Array(5)].map((_, i) => <div key={i} className="skeleton h-16 rounded-lg" />)}
              </div>
            ) : convs.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
                <InboxIcon className="w-10 h-10 text-muted-foreground/20 mb-3" />
                <p className="text-sm font-medium text-muted-foreground">
                  {filterReview ? "No conversations need review" : "No conversations yet"}
                </p>
              </div>
            ) : (
              convs.map((conv) => (
                <ConvItem
                  key={conv.id}
                  conv={conv}
                  selected={selected?.id === conv.id}
                  onClick={() => setSelected(conv)}
                />
              ))
            )}
          </div>
        </div>

        {/* ── Right panel: thread ── */}
        {!selected ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <MessageSquare className="w-12 h-12 text-muted-foreground/20 mb-3 mx-auto" />
              <p className="text-sm text-muted-foreground">Select a conversation</p>
            </div>
          </div>
        ) : (
          <div className="flex-1 flex flex-col min-w-0">

            {/* Thread header */}
            <div className="border-b border-border p-4 flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <p className="font-semibold">{selected.lead_name}</p>
                  <span className="text-muted-foreground text-sm">·</span>
                  <p className="text-sm text-muted-foreground">{selected.company}</p>
                  {selected.needs_human && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-orange-500/10 border border-orange-500/30 text-[10px] font-semibold text-orange-400 uppercase tracking-wide">
                      <AlertTriangle className="w-2.5 h-2.5" />
                      Needs Human
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <p className="text-xs text-muted-foreground">{selected.lead_email}</p>
                  <span className="text-muted-foreground">·</span>
                  <span className="text-xs text-muted-foreground capitalize">{selected.channel}</span>
                  {selected.sentiment && (
                    <>
                      <span className="text-muted-foreground">·</span>
                      <SentimentBadge sentiment={selected.sentiment} />
                    </>
                  )}
                </div>
                {selected.summary && (
                  <p className="text-xs text-muted-foreground/70 mt-1 italic">{selected.summary}</p>
                )}
              </div>

              {selected.needs_human && (
                <Button
                  size="sm"
                  variant="outline"
                  className="shrink-0 gap-1.5 border-emerald-500/40 text-emerald-400 hover:bg-emerald-500/10"
                  loading={resolving}
                  onClick={() => resolveMut(selected.id)}
                >
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  Resolve
                </Button>
              )}
            </div>

            {/* ── Human-flag alert ── */}
            {selected.needs_human && (
              <div className="mx-4 mt-3 rounded-lg border border-orange-500/30 bg-orange-500/5 px-4 py-2.5 flex items-center gap-2.5">
                <AlertTriangle className="w-4 h-4 text-orange-400 shrink-0" />
                <p className="text-xs text-orange-300">
                  The AI detected frustration or a complex objection and escalated this thread.
                  Review the messages below and send a personal reply.
                </p>
              </div>
            )}

            {/* ── Message thread ── */}
            <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3">
              {selected.messages.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-8">No messages yet</p>
              ) : (
                selected.messages.map((msg, i) => (
                  <MessageBubble key={i} msg={msg} />
                ))
              )}
              <div ref={threadEndRef} />
            </div>

            {/* ── Compose area ── */}
            <div className="border-t border-border p-4 space-y-3">
              {/* Agent reply compose */}
              <div className="flex gap-2">
                <textarea
                  value={reply}
                  onChange={(e) => setReply(e.target.value)}
                  placeholder="Type a reply to send from your SDR agent…"
                  rows={2}
                  className="flex-1 resize-none rounded-lg border border-border bg-secondary/30 px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/50 focus:border-primary/50"
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && reply.trim()) {
                      sendReplyMut({ leadId: selected.lead_id, message: reply.trim() });
                    }
                  }}
                />
                <Button
                  size="sm"
                  disabled={!reply.trim() || sendingReply}
                  loading={sendingReply}
                  onClick={() => sendReplyMut({ leadId: selected.lead_id, message: reply.trim() })}
                  className="h-auto px-3 gap-1.5 self-end"
                >
                  <Send className="w-3.5 h-3.5" />
                  Send Reply
                </Button>
              </div>

              {/* Demo: simulate lead reply */}
              <div>
                <button
                  onClick={() => setShowSimInput((v) => !v)}
                  className="flex items-center gap-1.5 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
                >
                  <ChevronDown className={cn("w-3 h-3 transition-transform", showSimInput && "rotate-180")} />
                  Simulate lead reply (demo)
                </button>

                {showSimInput && (
                  <Card className="mt-2 p-3 border-dashed border-violet-500/30 bg-violet-500/5">
                    <p className="text-[10px] text-violet-400 mb-2 font-medium uppercase tracking-wide">
                      Demo mode — simulates an inbound reply from the lead
                    </p>
                    <div className="flex gap-2">
                      <textarea
                        value={simReply}
                        onChange={(e) => setSimReply(e.target.value)}
                        placeholder="E.g. 'We don't have budget right now' or 'Tell me more about pricing'"
                        rows={2}
                        className="flex-1 resize-none rounded-lg border border-border bg-secondary/30 px-3 py-2 text-xs placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-violet-500/50 focus:border-violet-500/50"
                      />
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={!simReply.trim() || simulating}
                        loading={simulating}
                        onClick={() => simReplyMut({ leadId: selected.lead_id, message: simReply.trim() })}
                        className="h-auto px-3 self-end gap-1.5 border-violet-500/40 text-violet-400 hover:bg-violet-500/10"
                      >
                        <Bot className="w-3 h-3" />
                        Simulate
                      </Button>
                    </div>
                  </Card>
                )}
              </div>
            </div>

          </div>
        )}
      </div>
    </div>
  );
}
