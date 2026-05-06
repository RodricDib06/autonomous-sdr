import axios from "axios";
import type {
  TokenResponse,
  User,
  APIKey,
  APIKeyCreated,
  Lead,
  LeadDetail,
  LeadStats,
  HotLead,
  ImportResult,
  ImportHistory,
  QualityReport,
  HealthStatus,
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
