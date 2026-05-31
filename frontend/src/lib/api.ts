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
    api.post(`/leads/${leadId}/outreach/send`).then((r) => r.data),
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
      { params: { q, limit } }
    ).then((r) => r.data),

  powerBiExport: () =>
    api.get("/analytics/powerbi-export", { responseType: "blob" }).then((r) => r.data),

  retrainML: () => api.post("/analytics/ml/retrain").then((r) => r.data),
};

// ── Health ─────────────────────────────────────────────────────────────────────
export const healthApi = {
  check: () => axios.get<HealthStatus>(`${BASE_URL}/health`).then((r) => r.data),
};

// ── Config ─────────────────────────────────────────────────────────────────────
export const configApi = {
  getSlack: () => api.get("/config/slack").then((r) => r.data),
  setSlack: (webhook_url: string) =>
    api.post("/config/slack", null, { params: { webhook_url } }).then((r) => r.data),
  testSlack: () => api.post("/config/slack/test").then((r) => r.data),
  disableSlack: () => api.post("/config/slack/disable").then((r) => r.data),
};

export default api;
