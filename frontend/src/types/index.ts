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
  bant_scores: Record<string, number> | null;
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

export interface DuplicateReport {
  report: Array<{
    lead: Lead;
    duplicates: Array<{ lead: Lead; score: number; match_type: string }>;
  }>;
  generated_at: string;
}
