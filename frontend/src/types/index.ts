export interface User {
  id: string;
  email: string;
  role: "admin" | "manager" | "rep";
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface APIKey {
  id: string;
  name: string;
  key_prefix: string;
  is_active: boolean;
  created_at: string;
  last_used_at: string | null;
}

export interface APIKeyCreated extends APIKey {
  key: string;
}

export interface Lead {
  id: string;
  name: string;
  email: string;
  company: string;
  source: string | null;
  status: "pending" | "processing" | "complete" | "failed";
  created_at: string;
  updated_at: string | null;
  data_quality_score: number | null;
  completeness_score: number | null;
  tags: string[] | null;
  archived: boolean;
  final_verdict: "Hot" | "Warm" | "Cold" | null;
}

export interface Enrichment {
  job_title: string | null;
  seniority: string | null;
  company_size: string | null;
  industry: string | null;
  revenue_estimate: string | null;
  tech_stack: string[] | null;
  confidence: number | null;
  enrichment_source: string | null;
}

export interface Verdict {
  analysis_verdict: string | null;
  final_verdict: "Hot" | "Warm" | "Cold" | null;
  confidence_score: number | null;
  reasoning: string | null;
  bant_scores: Record<string, number> | null;  // now 0-1 floats instead of strings
  icp_match: boolean | null;
  validated: boolean | null;
  consistency_notes: string | null;
  flags: string[] | null;
}

export interface LeadDetail extends Lead {
  enrichment: Enrichment | null;
  verdict: Verdict | null;
}

export interface LeadStats {
  total_leads: number;
  completed: number;
  failed: number;
  processing: number;
  success_rate: number;
  verdict_breakdown: {
    hot: number;
    warm: number;
    cold: number;
  };
}

export interface HotLead {
  id: string;
  name: string;
  email: string;
  company: string;
  confidence: number;
  job_title: string | null;
  seniority: string | null;
  industry: string | null;
  reasoning: string | null;
}

export interface ImportHistory {
  id: string;
  filename: string;
  started_at: string;
  completed_at: string | null;
  total: number;
  successful: number;
  failed: number;
  duplicates: number;
  imported_by: string | null;
}

export interface ImportResult {
  total: number;
  successful: number;
  failed: number;
  duplicates: number;
  errors: string[];
}

export interface QualityReport {
  total_leads: number;
  avg_quality_score: number;
  avg_completeness_score: number;
  quality_distribution: {
    excellent: number;
    good: number;
    fair: number;
    poor: number;
  };
}

export interface HealthStatus {
  status: string;
  service: string;
  version: string;
  worker_active: boolean;
  worker_last_seen: string | null;
}

export interface LeadTrendPoint {
  day: string;
  total: number;
  hot: number;
  warm: number;
  cold: number;
}

export interface LeadTrend {
  days: number;
  data: LeadTrendPoint[];
}

export interface DuplicateReport {
  report: Array<{
    lead: Lead;
    duplicates: Array<{ lead: Lead; score: number; match_type: string }>;
  }>;
  generated_at: string;
}

// ── Phase 3 / 4 types ────────────────────────────────────────────────────────

export interface IntentSignal {
  rule: string;
  description: string;
  weight: number;
  triggered: boolean;
}

export interface IntentData {
  lead_id: string;
  score: number;
  signals: IntentSignal[];
  computed_at: string;
}

export interface OutreachEmail {
  id: string;
  lead_id: string;
  sequence_id: string | null;
  step_number: number;
  subject: string;
  body: string;
  status: "scheduled" | "sent" | "opened" | "replied" | "failed";
  scheduled_at: string;
  sent_at: string | null;
  opened_at: string | null;
  replied_at: string | null;
  error_message: string | null;
}

export interface BookingRequest {
  id: string;
  lead_id: string;
  status: "pending" | "confirmed" | "cancelled";
  scheduling_url: string | null;
  meeting_time: string | null;
  notes: string | null;
  created_at: string;
}

export interface ConversationMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  channel?: string;
}

export interface Conversation {
  id: string;
  lead_id: string;
  channel: string;
  messages: ConversationMessage[];
  summary: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface ABTestVariant {
  sequence_id: string;
  sequence_name: string;
  variant: string;
  emails_sent: number;
  opens: number;
  replies: number;
  conversions: number;
  open_rate: number;
  reply_rate: number;
  conversion_rate: number;
}

export interface ABTestResult {
  variants: ABTestVariant[];
  winner: string | null;
  p_value: number | null;
  significant: boolean;
  sample_size: number;
}

export interface OptimizationRun {
  id: string;
  created_at: string;
  leads_analysed: number;
  old_weights: Record<string, number>;
  new_weights: Record<string, number>;
  weight_delta: Record<string, number>;
  notes: string | null;
}

export interface PipelineTrace {
  lead_id: string;
  lead_name: string;
  status: string;
  final_verdict: string | null;
  nodes_executed: string[];
  agent_logs: Array<{
    id: string;
    agent_name: string;
    status: string;
    duration_ms: number | null;
    error_message: string | null;
    created_at: string;
  }>;
}

export interface SemanticSearchResult {
  conversation_id: string;
  lead_id: string;
  lead_name: string;
  channel: string;
  similarity: number | null;
  snippet: string;
  created_at: string;
}

export interface OutreachStats {
  total_sent: number;
  total_opened: number;
  total_replied: number;
  open_rate: number;
  reply_rate: number;
  emails_by_status: Record<string, number>;
}
