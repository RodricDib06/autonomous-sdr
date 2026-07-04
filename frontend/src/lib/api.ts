import axios from "axios";
import type {
  TokenResponse,
  User,
  APIKey,
  APIKeyCreated,
  Lead,
  LeadDetail,
  LeadStats,
  LeadTrend,
  CloseProbability,
  ICPConfig,
  ICPPreview,
  ICPEvaluation,
  EngagementDecay,
  CoolingLead,
  SimilarLead,
  WebEnrichment,
  CRMPushResult,
  MarketIntelligence,
  ABMultiAxis,
  HotLead,
  ImportResult,
  ImportHistory,
  QualityReport,
  HealthStatus,
  IntentData,
  OutreachEmail,
  BookingRequest,
  Conversation,
  ABTestResult,
  OptimizationRun,
  PipelineTrace,
  SemanticSearchResult,
  OutreachStats,
  DebateResult,
  PreCallBriefResult,
  TriggerSignal,
  SignalFeed,
  ReferralChain,
  InboxResponse,
  ChatResponse,
  FunnelData,
  AutonomyFeed,
  PipelineVelocity,
  RepPerformance,
  VerdictExplanation,
} from "../types";

const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

const api = axios.create({ baseURL: BASE_URL });

// ── Inject auth token on every request ──────────────────────────────────────
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// ── Auto-refresh on 401 ──────────────────────────────────────────────────────
api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const original = error.config;
    if (error.response?.status === 401 && !original._retry) {
      original._retry = true;
      const refresh = localStorage.getItem("refresh_token");
      if (refresh) {
        try {
          const { data } = await axios.post(`${BASE_URL}/auth/refresh`, {
            refresh_token: refresh,
          });
          localStorage.setItem("access_token", data.access_token);
          original.headers.Authorization = `Bearer ${data.access_token}`;
          return api(original);
        } catch {
          localStorage.clear();
          window.location.href = "/login";
        }
      } else {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

// ── Auth ─────────────────────────────────────────────────────────────────────
export const authApi = {
  login: (email: string, password: string) =>
    api.post<TokenResponse>("/auth/login", { email, password }).then((r) => r.data),

  register: (email: string, password: string, role = "rep") =>
    api.post<TokenResponse>("/auth/register", { email, password, role }).then((r) => r.data),

  me: () => api.get<User>("/auth/me").then((r) => r.data),

  changePassword: (current_password: string, new_password: string) =>
    api.put("/auth/me/password", { current_password, new_password }),

  listUsers: () => api.get<User[]>("/auth/users").then((r) => r.data),

  changeRole: (userId: string, role: string) =>
    api.put<User>(`/auth/users/${userId}/role`, null, { params: { role } }).then((r) => r.data),

  deactivateUser: (userId: string) => api.delete(`/auth/users/${userId}`),

  createApiKey: (name: string) =>
    api.post<APIKeyCreated>("/auth/api-keys", { name }).then((r) => r.data),

  listApiKeys: () => api.get<APIKey[]>("/auth/api-keys").then((r) => r.data),

  revokeApiKey: (id: string) => api.delete(`/auth/api-keys/${id}`),
};

// ── Leads ─────────────────────────────────────────────────────────────────────
export const leadsApi = {
  list: (skip = 0, limit = 100) =>
    api.get<Lead[]>("/leads", { params: { skip, limit } }).then((r) => r.data),

  get: (id: string) => api.get<LeadDetail>(`/leads/${id}`).then((r) => r.data),

  create: (payload: { name: string; email: string; company: string; source?: string }) =>
    api.post<Lead>("/leads", payload).then((r) => r.data),

  stats: () => api.get<LeadStats>("/leads/stats").then((r) => r.data),

  hot: (limit = 50) =>
    api.get<{ hot_leads: HotLead[]; count: number }>("/leads/hot", { params: { limit } }).then((r) => r.data),

  export: (format: "json" | "csv" | "hubspot" | "salesforce" = "csv") =>
    api.get("/leads/export", { params: { format }, responseType: "blob" }).then((r) => r.data),

  importCsv: (file: File, checkDuplicates = true) => {
    const fd = new FormData();
    fd.append("file", file);
    return api
      .post<ImportResult>("/leads/import-csv", fd, {
        params: { check_duplicates: checkDuplicates },
        headers: { "Content-Type": "multipart/form-data" },
      })
      .then((r) => r.data);
  },

  importHistory: (limit = 50) =>
    api
      .get<{ imports: ImportHistory[]; count: number }>("/leads/import-history", { params: { limit } })
      .then((r) => r.data),

  qualityReport: () => api.get<QualityReport>("/leads/quality-report").then((r) => r.data),

  batch: (action: string, lead_ids: string[], payload: Record<string, unknown> = {}) =>
    api.post("/leads/batch", { action, lead_ids, payload }).then((r) => r.data),

  duplicateReport: () =>
    api.get("/leads/duplicates/report").then((r) => r.data),

  reprocessFailed: () =>
    api.post<{ requeued: number; message: string }>("/leads/reprocess-failed").then((r) => r.data),

  trend: (days = 30) =>
    api.get<LeadTrend>("/leads/trend", { params: { days } }).then((r) => r.data),

  closeProbability: (id: string) =>
    api.get<CloseProbability>(`/leads/${id}/close-probability`).then((r) => r.data),
};

// ── Pipeline ──────────────────────────────────────────────────────────────────
export const pipelineApi = {
  trace: (leadId: string) =>
    api.get<PipelineTrace>(`/leads/${leadId}/pipeline-trace`).then((r) => r.data),
};

// ── Intent ────────────────────────────────────────────────────────────────────
export const intentApi = {
  get: (leadId: string) =>
    api.get<IntentData>(`/leads/${leadId}/intent`).then((r) => r.data),
};

// ── Outreach ──────────────────────────────────────────────────────────────────
export const outreachApi = {
  list: (leadId: string) =>
    api.get<{ emails: OutreachEmail[]; count: number }>(`/leads/${leadId}/outreach`).then((r) => r.data),

  stats: () =>
    api.get<OutreachStats>("/outreach/stats").then((r) => r.data),

  sendNow: (leadId: string) =>
    api.post(`/leads/${leadId}/outreach`).then((r) => r.data),
};

// ── Booking ───────────────────────────────────────────────────────────────────
export const bookingApi = {
  list: (leadId: string) =>
    api.get<{ bookings: BookingRequest[]; count: number }>(`/leads/${leadId}/bookings`).then((r) => r.data),
};

// ── Conversations ─────────────────────────────────────────────────────────────
export const conversationsApi = {
  list: (leadId: string) =>
    api.get<{ conversations: Conversation[]; count: number }>(`/leads/${leadId}/conversations`).then((r) => r.data),
};

// ── A/B Tests ─────────────────────────────────────────────────────────────────
export const abTestApi = {
  results: () => api.get<ABTestResult>("/ab-tests/results").then((r) => r.data),
  promoteWinner: (sequenceId: string) =>
    api.post(`/ab-tests/${sequenceId}/promote`).then((r) => r.data),
};

// ── Optimization ──────────────────────────────────────────────────────────────
export const optimizationApi = {
  history: (limit = 10) =>
    api.get<{ runs: OptimizationRun[]; count: number }>("/optimization/history", { params: { limit } }).then((r) => r.data),

  currentWeights: () =>
    api.get<Record<string, number>>("/optimization/weights").then((r) => r.data),

  runNow: () => api.post("/optimization/run").then((r) => r.data),
};

// ── Analytics ─────────────────────────────────────────────────────────────────
export const analyticsApi = {
  semanticSearch: (q: string, limit = 10) =>
    api.get<{ results: SemanticSearchResult[]; count: number; query: string }>(
      "/analytics/semantic-search",
      { params: { query: q, limit } }
    ).then((r) => r.data),

  powerBiExport: () =>
    api.get("/analytics/powerbi-export", { responseType: "blob" }).then((r) => r.data),

  retrainML: () => api.post("/analytics/ml/retrain").then((r) => r.data),

  pipelineVelocity: () =>
    api.get<PipelineVelocity>("/analytics/pipeline-velocity").then((r) => r.data),

  repPerformance: () =>
    api.get<RepPerformance>("/analytics/rep-performance").then((r) => r.data),

  verdictExplanation: (leadId: string) =>
    api.get<VerdictExplanation>(`/leads/${leadId}/verdict-explanation`).then((r) => r.data),
};

// ── ICP ───────────────────────────────────────────────────────────────────────
export const icpApi = {
  get: () => api.get<ICPConfig>("/icp").then((r) => r.data),
  update: (payload: Partial<Omit<ICPConfig, "configured" | "updated_at" | "updated_by_id">>) =>
    api.put<ICPConfig>("/icp", payload).then((r) => r.data),
  preview: () => api.get<ICPPreview>("/icp/preview").then((r) => r.data),
  evaluate: (leadId: string) =>
    api.get<ICPEvaluation>(`/leads/${leadId}/icp-evaluation`).then((r) => r.data),
};

// ── Engagement decay ──────────────────────────────────────────────────────────
export const decayApi = {
  cooling: (limit = 20) =>
    api.get<{ leads: CoolingLead[]; count: number }>("/leads/cooling", { params: { limit } }).then((r) => r.data),
  leadDecay: (leadId: string) =>
    api.get<EngagementDecay>(`/leads/${leadId}/engagement-decay`).then((r) => r.data),
};

// ── Health ─────────────────────────────────────────────────────────────────────
export const healthApi = {
  check: () => axios.get<HealthStatus>(`${BASE_URL}/health`).then((r) => r.data),
};

// ── CRM push ──────────────────────────────────────────────────────────────────
export const crmApi = {
  push: (leadId: string, format: "hubspot" | "salesforce" | "pipedrive") =>
    api.post<CRMPushResult>(`/leads/${leadId}/crm-push`, null, { params: { format } }).then((r) => r.data),
};

// ── Similar leads + web enrichment ────────────────────────────────────────────
export const enrichmentApi = {
  similar: (leadId: string, limit = 5) =>
    api.get<{ lead_id: string; similar: SimilarLead[]; count: number }>(`/leads/${leadId}/similar`, { params: { limit } }).then((r) => r.data),
  webEnrich: (leadId: string) =>
    api.post<WebEnrichment>(`/leads/${leadId}/web-enrich`).then((r) => r.data),
};

// ── Market intelligence ────────────────────────────────────────────────────────
export const marketApi = {
  intelligence: () => api.get<MarketIntelligence>("/analytics/market-intelligence").then((r) => r.data),
};

// ── Multi-axis A/B ─────────────────────────────────────────────────────────────
export const abMultiApi = {
  axes: () => api.get<ABMultiAxis>("/ab-tests/multi-axis").then((r) => r.data),
};

// ── Referral chain ────────────────────────────────────────────────────────────
export const referralChainApi = {
  get: (leadId: string) =>
    api.get<ReferralChain>(`/leads/${leadId}/referral-chain`).then((r) => r.data),
};

// ── Debate (adversarial BANT) ─────────────────────────────────────────────────
export const debateApi = {
  get: (leadId: string) =>
    api.get<DebateResult>(`/leads/${leadId}/debate`).then((r) => r.data),
};

// ── Pre-call brief ─────────────────────────────────────────────────────────────
export const briefApi = {
  get: (leadId: string) =>
    api.get<PreCallBriefResult>(`/leads/${leadId}/pre-call-brief`).then((r) => r.data),
};

// ── Trigger signal feed ────────────────────────────────────────────────────────
export const signalApi = {
  feed: (params?: { limit?: number; signal_type?: string }) =>
    api.get<SignalFeed>("/analytics/signal-feed", { params }).then((r) => r.data),
  forLead: (leadId: string) =>
    api.get<{ signals: TriggerSignal[]; count: number }>(`/leads/${leadId}/trigger-signals`).then((r) => r.data),
};

// ── Inbox ─────────────────────────────────────────────────────────────────────
export const inboxApi = {
  list: (params?: { needs_human?: boolean; limit?: number }) =>
    api.get<InboxResponse>("/inbox", { params }).then((r) => r.data),
  resolve: (convId: string) =>
    api.post<{ status: string; conversation_id: string }>(`/conversations/${convId}/resolve`).then((r) => r.data),
  reply: (leadId: string, message: string, channel = "email") =>
    api.post<ChatResponse>(`/leads/${leadId}/chat`, null, {
      params: { channel, mode: "reply", message },
    }).then((r) => r.data),
  simulateReply: (leadId: string, message: string, channel = "email") =>
    api.post<ChatResponse>(`/leads/${leadId}/chat`, null, {
      params: { channel, mode: "reply", message },
    }).then((r) => r.data),
};

// ── Revenue funnel ─────────────────────────────────────────────────────────────
export const funnelApi = {
  get: (acv?: number) =>
    api.get<FunnelData>("/analytics/funnel", { params: acv ? { acv } : {} }).then((r) => r.data),
};

// ── Demo seeder ────────────────────────────────────────────────────────────────
export const seedApi = {
  demo: () => api.post<{ status: string; message: string }>("/seed/demo").then((r) => r.data),
};

// ── SSE helpers ───────────────────────────────────────────────────────────────
export const SSE_BASE = BASE_URL;

// ── Config ─────────────────────────────────────────────────────────────────────
export const configApi = {
  getSlack: () => api.get("/config/slack").then((r) => r.data),
  setSlack: (webhook_url: string) =>
    api.post("/config/slack", null, { params: { webhook_url } }).then((r) => r.data),
  testSlack: () => api.post("/config/slack/test").then((r) => r.data),
  disableSlack: () => api.post("/config/slack/disable").then((r) => r.data),
};

// ── Autonomy activity feed ─────────────────────────────────────────────────────
export const autonomyApi = {
  feed: (hours = 24) =>
    api.get<AutonomyFeed>("/autonomy-feed", { params: { hours } }).then((r) => r.data),
};

// ── Approvals — human-in-the-loop autonomy dial ───────────────────────────────
export type AutonomyMode = "draft" | "approve" | "auto";

export interface PendingEmail {
  id: string;
  lead_id: string;
  lead_name: string | null;
  lead_email: string | null;
  company: string | null;
  step_number: number;
  subject: string;
  body: string;
  quality_score: number | null;
  scheduled_at: string | null;
  created_at: string | null;
}

export const approvalsApi = {
  getAutonomy: () =>
    api.get<{ mode: AutonomyMode; modes: AutonomyMode[]; pending_count: number }>("/outreach/autonomy").then((r) => r.data),
  setAutonomy: (mode: AutonomyMode) =>
    api.put<{ mode: AutonomyMode }>("/outreach/autonomy", { mode }).then((r) => r.data),
  list: () =>
    api.get<{ total: number; mode: AutonomyMode; emails: PendingEmail[] }>("/outreach/approvals").then((r) => r.data),
  approve: (id: string, edits?: { subject?: string; body?: string }) =>
    api.post(`/outreach/approvals/${id}/approve`, edits ?? {}).then((r) => r.data),
  reject: (id: string, reason?: string) =>
    api.post(`/outreach/approvals/${id}/reject`, { reason }).then((r) => r.data),
  approveAll: () =>
    api.post<{ approved: number }>("/outreach/approvals/approve-all").then((r) => r.data),
};

// ── Sequences — cadence authoring ─────────────────────────────────────────────
export interface SequenceStep {
  step: number;
  delay_days: number;
  subject_template: string;
  body_template: string;
}

export interface Sequence {
  id: string;
  name: string;
  ab_variant: string | null;
  is_active: boolean;
  is_global: boolean;
  steps: SequenceStep[];
  emails_sent: number;
  conversions: number;
  created_at: string | null;
}

export const sequencesApi = {
  list: () =>
    api.get<{ sequences: Sequence[]; total: number }>("/sequences").then((r) => r.data),
  create: (payload: { name: string; ab_variant: string | null; steps: SequenceStep[] }) =>
    api.post<Sequence>("/sequences", payload).then((r) => r.data),
  update: (id: string, payload: { name?: string; ab_variant?: string | null; steps?: SequenceStep[]; is_active?: boolean }) =>
    api.put<Sequence & { cloned_from_global?: boolean }>(`/sequences/${id}`, payload).then((r) => r.data),
  deactivate: (id: string) =>
    api.delete(`/sequences/${id}`).then((r) => r.data),
};

// ── Compliance — suppression list + send guardrails ───────────────────────────
export interface SuppressionEntry {
  id: string;
  value: string;
  kind: "email" | "domain";
  source: string;
  reason: string | null;
  lead_id: string | null;
  created_at: string | null;
}

export interface GuardrailStatus {
  can_send: boolean;
  reason: string;
  sent_last_24h: number;
  daily_limit: number;
  window_start_hour_utc: number;
  window_end_hour_utc: number;
  weekdays_only: boolean;
  suppression_count: number;
}

export const complianceApi = {
  guardrails: () =>
    api.get<GuardrailStatus>("/outreach/guardrails").then((r) => r.data),
  listSuppressions: (limit = 200) =>
    api.get<{ total: number; entries: SuppressionEntry[] }>("/suppressions", { params: { limit } }).then((r) => r.data),
  addSuppression: (value: string, reason?: string) =>
    api.post<{ id: string; value: string; kind: string; cancelled_emails: number }>("/suppressions", { value, reason }).then((r) => r.data),
  removeSuppression: (id: string) =>
    api.delete(`/suppressions/${id}`).then((r) => r.data),
};

export default api;
