import { http, HttpResponse } from 'msw';

const API_BASE_URL = 'http://localhost:8000';

export const handlers = [
  // ── Auth ──────────────────────────────────────────────────────────────────
  http.post(`${API_BASE_URL}/auth/login`, () =>
    HttpResponse.json({
      access_token: 'test-jwt-token',
      refresh_token: 'test-refresh-token',
      token_type: 'bearer',
      expires_in: 3600,
      user: mockUser,
    })
  ),

  http.post(`${API_BASE_URL}/auth/register`, () =>
    HttpResponse.json({
      access_token: 'test-jwt-token',
      refresh_token: 'test-refresh-token',
      token_type: 'bearer',
      expires_in: 3600,
      user: { ...mockUser, id: 'user-new', email: 'newuser@example.com', last_login_at: null },
    })
  ),

  http.post(`${API_BASE_URL}/auth/refresh`, () =>
    HttpResponse.json({ access_token: 'new-access-token' })
  ),

  http.get(`${API_BASE_URL}/auth/me`, () => HttpResponse.json(mockUser)),

  http.put(`${API_BASE_URL}/auth/me/password`, () => HttpResponse.json({ ok: true })),

  http.get(`${API_BASE_URL}/auth/users`, () => HttpResponse.json([mockUser])),

  http.put(`${API_BASE_URL}/auth/users/:id/role`, () => HttpResponse.json(mockUser)),

  http.delete(`${API_BASE_URL}/auth/users/:id`, () => HttpResponse.json({ ok: true })),

  http.get(`${API_BASE_URL}/auth/api-keys`, () => HttpResponse.json([])),

  http.post(`${API_BASE_URL}/auth/api-keys`, () =>
    HttpResponse.json({ id: 'key-1', name: 'Test Key', key_prefix: 'sk_test', key: 'sk_test_full_key', is_active: true, created_at: '2024-01-01T00:00:00Z', last_used_at: null })
  ),

  http.delete(`${API_BASE_URL}/auth/api-keys/:id`, () => HttpResponse.json({ ok: true })),

  // ── Leads ──────────────────────────────────────────────────────────────────
  // Backend returns list[LeadResponse] (array) directly
  http.get(`${API_BASE_URL}/leads`, ({ request }) => {
    const url = new URL(request.url);
    const skip = parseInt(url.searchParams.get('skip') || '0');
    const limit = parseInt(url.searchParams.get('limit') || '100');
    const verdict = url.searchParams.get('verdict');

    let leads = mockLeads;
    if (verdict) {
      leads = leads.filter((l) => l.final_verdict === verdict);
    }
    return HttpResponse.json(leads.slice(skip, skip + limit));
  }),

  http.post(`${API_BASE_URL}/leads`, async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({
      id: 'lead-new',
      ...body,
      status: 'pending',
      created_at: new Date().toISOString(),
      updated_at: null,
      data_quality_score: null,
      completeness_score: null,
      tags: [],
      archived: false,
      final_verdict: null,
    });
  }),

  // Specific routes before :id wildcard
  http.get(`${API_BASE_URL}/leads/stats`, () =>
    HttpResponse.json({
      total_leads: 150,
      completed: 120,
      failed: 5,
      processing: 25,
      success_rate: 0.8,
      verdict_breakdown: { hot: 12, warm: 35, cold: 73 },
    })
  ),

  http.get(`${API_BASE_URL}/leads/hot`, ({ request }) => {
    const url = new URL(request.url);
    const limit = parseInt(url.searchParams.get('limit') || '50');
    return HttpResponse.json({ hot_leads: mockHotLeads.slice(0, limit), count: mockHotLeads.length });
  }),

  http.get(`${API_BASE_URL}/leads/quality-report`, () =>
    HttpResponse.json({
      total_leads: 150,
      avg_quality_score: 0.72,
      avg_completeness_score: 0.85,
      quality_distribution: { excellent: 20, good: 60, fair: 50, poor: 20 },
    })
  ),

  http.get(`${API_BASE_URL}/leads/export`, () =>
    HttpResponse.text('name,email,company\nJohn Doe,john@example.com,Tech Corp')
  ),

  http.get(`${API_BASE_URL}/leads/import-history`, ({ request }) => {
    const url = new URL(request.url);
    const limit = parseInt(url.searchParams.get('limit') || '50');
    return HttpResponse.json({ imports: mockImportHistory.slice(0, limit), count: mockImportHistory.length });
  }),

  http.get(`${API_BASE_URL}/leads/duplicates/report`, () =>
    HttpResponse.json({ report: [], generated_at: new Date().toISOString() })
  ),

  http.get(`${API_BASE_URL}/leads/trend`, () =>
    HttpResponse.json({
      data: [
        { day: '2024-01-10', total: 8, hot: 3, warm: 3, cold: 2 },
        { day: '2024-01-11', total: 12, hot: 5, warm: 4, cold: 3 },
        { day: '2024-01-12', total: 6, hot: 2, warm: 2, cold: 2 },
      ],
      days: 30,
    })
  ),

  http.post(`${API_BASE_URL}/leads/import-csv`, () =>
    HttpResponse.json({ total: 50, successful: 47, failed: 0, duplicates: 3, errors: [] })
  ),

  http.post(`${API_BASE_URL}/leads/reprocess-failed`, () =>
    HttpResponse.json({ requeued: 3, message: '3 failed leads re-queued' })
  ),

  http.post(`${API_BASE_URL}/leads/batch`, async ({ request }) => {
    const body = (await request.json()) as { action: string; lead_ids: string[] };
    return HttpResponse.json({ action: body.action, affected: body.lead_ids.length });
  }),

  http.get(`${API_BASE_URL}/leads/:id`, ({ params }) => {
    const lead = mockLeads.find((l) => l.id === params.id);
    if (!lead) return HttpResponse.json({ detail: 'Not found' }, { status: 404 });
    return HttpResponse.json({ ...lead, enrichment: mockEnrichment, verdict: mockVerdict });
  }),

  http.get(`${API_BASE_URL}/leads/:id/history`, () =>
    HttpResponse.json(mockHistory)
  ),

  http.get(`${API_BASE_URL}/leads/:id/intent`, () =>
    HttpResponse.json({
      lead_id: 'lead-1',
      score: 0.78,
      signals: [
        { rule: 'recent_funding', description: 'Recently raised Series B', weight: 0.4, triggered: true },
        { rule: 'hiring_signal', description: 'Actively hiring sales reps', weight: 0.3, triggered: true },
      ],
      computed_at: '2024-01-15T12:00:00Z',
    })
  ),

  http.get(`${API_BASE_URL}/leads/:id/outreach`, () =>
    HttpResponse.json({ emails: [], count: 0 })
  ),

  http.post(`${API_BASE_URL}/leads/:id/outreach/send`, () =>
    HttpResponse.json({ success: true })
  ),

  http.get(`${API_BASE_URL}/leads/:id/bookings`, () =>
    HttpResponse.json({ bookings: [], count: 0 })
  ),

  http.get(`${API_BASE_URL}/leads/:id/conversations`, () =>
    HttpResponse.json({ conversations: [], count: 0 })
  ),

  http.get(`${API_BASE_URL}/leads/:id/pipeline-trace`, ({ params }) =>
    HttpResponse.json({
      lead_id: params.id,
      lead_name: 'John Doe',
      status: 'complete',
      final_verdict: 'Hot',
      nodes_executed: ['orchestrate', 'enrich', 'analyze', 'validate'],
      agent_logs: [
        { id: 'log-1', agent_name: 'Enrich Agent', status: 'success', error_message: null, duration_ms: 245 },
        { id: 'log-2', agent_name: 'Score Agent', status: 'failed', error_message: 'API timeout', duration_ms: null },
        { id: 'log-3', agent_name: 'Validate Agent', status: 'running', error_message: null, duration_ms: null },
      ],
    })
  ),

  http.get(`${API_BASE_URL}/leads/:id/close-probability`, () =>
    HttpResponse.json({
      lead_id: 'lead-1',
      probability: 0.73,
      bant_score: 0.87,
      divergence: 0.14,
      divergence_note: 'BANT score and ML model diverge slightly — trust ML',
      feature_importances: {
        'bant_budget': 0.35,
        'company_size_score': 0.22,
        'seniority_rank': -0.15,
      },
      model_info: {
        trained_on: 450,
        converted: 180,
        lost: 270,
        trained_at: '2024-01-01T00:00:00Z',
      },
      fallback: false,
    })
  ),

  http.get(`${API_BASE_URL}/leads/:id/similar`, () =>
    HttpResponse.json({
      lead_id: 'lead-1',
      similar: [
        { id: 'lead-2', name: 'Jane Smith', company: 'Innovation Labs', final_verdict: 'Warm', similarity: 0.87 },
      ],
      count: 1,
    })
  ),

  http.post(`${API_BASE_URL}/leads/:id/crm-push`, ({ request }) => {
    const url = new URL(request.url);
    const format = url.searchParams.get('format') ?? 'hubspot';
    return HttpResponse.json({ lead_id: 'lead-1', format, payload: { name: 'John Doe' } });
  }),

  http.post(`${API_BASE_URL}/leads/:id/web-enrich`, () =>
    HttpResponse.json({
      lead_id: 'lead-1',
      domain: 'techcorp.com',
      signals: [{ text: 'Series B announcement in 2024' }],
      tech_stack: ['React', 'AWS'],
      pages_fetched: 3,
      error: null,
    })
  ),

  // ── Outreach ───────────────────────────────────────────────────────────────
  http.get(`${API_BASE_URL}/outreach/stats`, () =>
    HttpResponse.json({
      total_sent: 85,
      total_opened: 35,
      total_replied: 12,
      open_rate: 0.41,
      reply_rate: 0.14,
      emails_by_status: { scheduled: 10, sent: 85, opened: 35, replied: 12, failed: 2 },
    })
  ),

  // ── A/B Tests ──────────────────────────────────────────────────────────────
  http.get(`${API_BASE_URL}/ab-tests/results`, () =>
    HttpResponse.json({
      variants: [
        {
          sequence_id: 'seq-1',
          sequence_name: 'Cold Outreach A',
          variant: 'A',
          emails_sent: 100,
          opens: 35,
          replies: 8,
          conversions: 1,
          open_rate: 0.35,
          reply_rate: 0.08,
          conversion_rate: 0.01,
        },
        {
          sequence_id: 'seq-2',
          sequence_name: 'Cold Outreach B',
          variant: 'B',
          emails_sent: 100,
          opens: 42,
          replies: 12,
          conversions: 2,
          open_rate: 0.42,
          reply_rate: 0.12,
          conversion_rate: 0.02,
        },
      ],
      winner: 'B',
      p_value: 0.042,
      significant: true,
      sample_size: 200,
    })
  ),

  http.post(`${API_BASE_URL}/ab-tests/:id/promote`, () =>
    HttpResponse.json({ success: true })
  ),

  http.get(`${API_BASE_URL}/ab-tests/multi-axis`, () =>
    HttpResponse.json({
      send_time: [
        { label: 'morning', sent: 120, opened: 48, replied: 14, open_rate: 0.40, reply_rate: 0.12 },
        { label: 'afternoon', sent: 80, opened: 28, replied: 8, open_rate: 0.35, reply_rate: 0.10 },
      ],
      subject_style: [
        { label: 'question', sent: 100, opened: 45, replied: 15, open_rate: 0.45, reply_rate: 0.15 },
        { label: 'statement', sent: 100, opened: 31, replied: 7, open_rate: 0.31, reply_rate: 0.07 },
      ],
      message_length: [
        { label: 'short', sent: 90, opened: 41, replied: 12, open_rate: 0.46, reply_rate: 0.13 },
        { label: 'medium', sent: 110, opened: 35, replied: 10, open_rate: 0.32, reply_rate: 0.09 },
      ],
      total_emails_analysed: 200,
    })
  ),

  // ── Optimization ───────────────────────────────────────────────────────────
  http.get(`${API_BASE_URL}/optimization/history`, () =>
    HttpResponse.json({
      runs: [
        {
          id: 'opt-1',
          created_at: '2024-01-10T00:00:00Z',
          leads_analysed: 120,
          old_weights: { budget: 0.25, authority: 0.25, need: 0.25, timeline: 0.25 },
          new_weights: { budget: 0.3, authority: 0.2, need: 0.35, timeline: 0.15 },
          weight_delta: { budget: 0.05, authority: -0.05, need: 0.1, timeline: -0.1 },
          notes: null,
        },
      ],
      count: 1,
    })
  ),

  http.get(`${API_BASE_URL}/optimization/weights`, () =>
    HttpResponse.json({ budget: 0.3, authority: 0.2, need: 0.35, timeline: 0.15 })
  ),

  http.post(`${API_BASE_URL}/optimization/run`, () =>
    HttpResponse.json({ ok: true })
  ),

  // ── Analytics ──────────────────────────────────────────────────────────────
  http.get(`${API_BASE_URL}/analytics/semantic-search`, () =>
    HttpResponse.json({ results: [], count: 0, query: '' })
  ),

  http.get(`${API_BASE_URL}/analytics/powerbi-export`, () =>
    HttpResponse.text('{}')
  ),

  http.get(`${API_BASE_URL}/analytics/market-intelligence`, () =>
    HttpResponse.json({
      segments: [
        { industry: 'Technology', seniority: 'VP', total: 45, hot: 22, warm: 15, cold: 8, hot_rate: 0.49, warm_rate: 0.33, lift: 2.1 },
        { industry: 'FinTech', seniority: 'C-Level', total: 30, hot: 18, warm: 8, cold: 4, hot_rate: 0.60, warm_rate: 0.27, lift: 2.8 },
      ],
      top_industries: [
        { industry: 'Technology', total: 60, hot: 28, warm: 20, cold: 12, hot_rate: 0.47, lift: 1.9 },
      ],
      global_stats: { total: 150, hot: 45, warm: 60, cold: 45, global_hot_rate: 0.30 },
      computed_at: '2024-01-15T12:00:00Z',
    })
  ),

  // ── Config ─────────────────────────────────────────────────────────────────
  http.get(`${API_BASE_URL}/config/slack`, () =>
    HttpResponse.json({ enabled: false, webhook_url: null })
  ),

  http.post(`${API_BASE_URL}/config/slack`, () =>
    HttpResponse.json({ enabled: true })
  ),

  http.post(`${API_BASE_URL}/config/slack/test`, () =>
    HttpResponse.json({ ok: true })
  ),

  http.post(`${API_BASE_URL}/config/slack/disable`, () =>
    HttpResponse.json({ enabled: false })
  ),

  // ── Decay / cooling leads ──────────────────────────────────────────────────
  http.get(`${API_BASE_URL}/leads/cooling`, () =>
    HttpResponse.json({ leads: [], count: 0 })
  ),

  http.get(`${API_BASE_URL}/leads/:id/engagement-decay`, () =>
    HttpResponse.json({
      lead_id: 'lead-1',
      days_since_contact: 12,
      decay_score: 0.35,
      urgency: 'urgent',
      recommended_action: 'Follow up immediately',
    })
  ),

  // ── ICP ────────────────────────────────────────────────────────────────────
  http.get(`${API_BASE_URL}/icp`, () =>
    HttpResponse.json(mockICP)
  ),

  http.put(`${API_BASE_URL}/icp`, async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({ ...mockICP, ...body, updated_at: new Date().toISOString() });
  }),

  http.get(`${API_BASE_URL}/icp/preview`, () =>
    HttpResponse.json(mockICPPreview)
  ),

  http.get(`${API_BASE_URL}/leads/:id/icp-evaluation`, () =>
    HttpResponse.json({ match: true, score: 0.88, reasons: ['Industry match', 'Seniority match'] })
  ),

  // ── Seed ───────────────────────────────────────────────────────────────────
  http.post(`${API_BASE_URL}/seed/demo`, () =>
    HttpResponse.json({ status: 'seeding', message: 'Demo data loading in background' })
  ),

  // ── Health ─────────────────────────────────────────────────────────────────
  http.get(`${API_BASE_URL}/health`, () =>
    HttpResponse.json({ status: 'healthy', service: 'autonomous-sdr', version: '1.0.0', worker_active: true, worker_last_seen: new Date().toISOString() })
  ),
];

// ── Shared mock data ───────────────────────────────────────────────────────

export const mockUser = {
  id: 'user-1',
  email: 'test@example.com',
  role: 'rep' as const,
  is_active: true,
  created_at: '2024-01-01T00:00:00Z',
  last_login_at: '2024-01-15T12:00:00Z',
};

export const mockLeads = [
  {
    id: 'lead-1',
    name: 'John Doe',
    email: 'john@example.com',
    company: 'Tech Corp',
    source: 'form',
    status: 'complete' as const,
    created_at: '2024-01-10T00:00:00Z',
    updated_at: '2024-01-15T00:00:00Z',
    data_quality_score: 0.95,
    completeness_score: 0.98,
    tags: ['vip', 'tech'],
    archived: false,
    final_verdict: 'Hot' as const,
  },
  {
    id: 'lead-2',
    name: 'Jane Smith',
    email: 'jane@example.com',
    company: 'Innovation Labs',
    source: 'linkedin',
    status: 'complete' as const,
    created_at: '2024-01-12T00:00:00Z',
    updated_at: '2024-01-14T00:00:00Z',
    data_quality_score: 0.75,
    completeness_score: 0.82,
    tags: ['startup'],
    archived: false,
    final_verdict: 'Warm' as const,
  },
  {
    id: 'lead-3',
    name: 'Bob Wilson',
    email: 'bob@example.com',
    company: 'Enterprise Solutions',
    source: 'email',
    status: 'processing' as const,
    created_at: '2024-01-13T00:00:00Z',
    updated_at: '2024-01-13T00:00:00Z',
    data_quality_score: 0.55,
    completeness_score: 0.60,
    tags: [],
    archived: false,
    final_verdict: 'Cold' as const,
  },
];

export const mockHotLeads = [
  {
    id: 'lead-1',
    name: 'John Doe',
    email: 'john@example.com',
    company: 'Tech Corp',
    confidence: 0.95,
    job_title: 'Senior VP Sales',
    seniority: 'executive',
    industry: 'Technology',
    reasoning: 'High-ranking decision maker at well-funded tech company',
  },
];

const mockEnrichment = {
  job_title: 'Senior VP Sales',
  seniority: 'executive',
  company_size: '500-1000',
  industry: 'Technology',
  revenue_estimate: '$100M-$500M',
  tech_stack: ['Salesforce', 'HubSpot', 'Slack'],
  confidence: 0.92,
  enrichment_source: 'hunter.io',
};

const mockVerdict = {
  analysis_verdict: 'Qualified prospect with strong budget signals',
  final_verdict: 'Hot',
  confidence_score: 0.89,
  reasoning: 'High-ranking decision maker at well-funded tech company',
  bant_scores: { budget: 0.95, authority: 0.85, need: 0.92, timeline: 0.78 },
  icp_match: true,
  validated: true,
  consistency_notes: null,
  flags: [],
};

const mockHistory = [
  {
    id: 'hist-1',
    event_type: 'status_changed',
    old_value: 'processing',
    new_value: 'complete',
    changed_by: 'system',
    changed_at: '2024-01-15T10:00:00Z',
  },
];

const mockImportHistory = [
  {
    id: 'import-1',
    filename: 'leads_2024_01_15.csv',
    started_at: '2024-01-15T10:00:00Z',
    completed_at: '2024-01-15T10:02:30Z',
    total: 50,
    successful: 47,
    failed: 0,
    duplicates: 3,
    imported_by: 'test@example.com',
  },
];

export const mockICP = {
  industries: ['SaaS', 'FinTech'],
  seniority_levels: ['VP', 'C-Level'],
  excluded_industries: ['Government'],
  min_employees: 50,
  max_employees: 1000,
  updated_at: '2024-01-15T12:00:00Z',
  updated_by_id: 'user-1',
};

export const mockICPPreview = {
  matched: 45,
  total: 150,
  hot: 12,
  warm: 20,
  cold: 13,
  unconfigured: false,
};

export const mockCoolingLeads = [
  {
    id: 'lead-1',
    name: 'Alice Chen',
    email: 'alice@startup.io',
    company: 'Startup IO',
    job_title: 'VP Engineering',
    decay: { days_since_contact: 10, decay_score: 0.3, urgency: 'urgent', recommended_action: 'Call now' },
  },
  {
    id: 'lead-2',
    name: 'Bob Kim',
    email: 'bob@scale.co',
    company: 'Scale Co',
    job_title: null,
    decay: { days_since_contact: 8, decay_score: 0.5, urgency: 'warning', recommended_action: 'Send follow-up' },
  },
];
