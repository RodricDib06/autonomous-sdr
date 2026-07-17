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
    return HttpResponse.json({
      ...lead,
      enrichment: mockEnrichment,
      verdict: mockVerdict,
      email_verification_status: 'valid',
      email_verified_at: '2026-07-14T09:00:00Z',
      email_verification_reason: 'All checks passed',
    });
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

  // ── ROI ─────────────────────────────────────────────────────────────────────
  http.get(`${API_BASE_URL}/analytics/roi`, () =>
    HttpResponse.json({
      window_days: 90,
      assumptions: { acv_usd: 25000, sdr_annual_cost_usd: 75000, human_sdr_leads_per_year: 3000 },
      activity: { leads_processed: 150, hot_leads: 45, emails_sent: 210, meetings_booked: 18, conversions: 9, llm_cost_usd: 4.2 },
      unit_economics: { ai_cost_per_lead_usd: 0.028, human_cost_per_lead_usd: 25, cost_per_hot_lead_usd: 0.093, cost_per_meeting_usd: 0.23, savings_multiple: 892.9 },
      projections: { annualized_lead_volume: 608, projected_annual_ai_cost_usd: 17.03, projected_annual_human_cost_usd: 15208, projected_annual_savings_usd: 15191, pipeline_value_usd: 225000 },
    })
  ),

  // ── Sequences — cadence authoring ──────────────────────────────────────────
  http.get(`${API_BASE_URL}/sequences`, () =>
    HttpResponse.json({
      total: 2,
      sequences: [
        {
          id: 'seq-1', name: 'Standard 3-Step (Variant A)', ab_variant: 'A', is_active: true,
          is_global: true, emails_sent: 42, conversions: 6, created_at: '2026-01-01T00:00:00Z',
          steps: [
            { step: 1, delay_days: 0, subject_template: 'Quick question about {company}', body_template: 'Hi {first_name}…' },
            { step: 2, delay_days: 3, subject_template: 'Re: {company}', body_template: 'Following up…' },
          ],
        },
        {
          id: 'seq-2', name: 'My Custom Cadence', ab_variant: 'C', is_active: true,
          is_global: false, emails_sent: 10, conversions: 2, created_at: '2026-06-01T00:00:00Z',
          steps: [
            { step: 1, delay_days: 0, subject_template: 'Hello {first_name}', body_template: 'Body…' },
          ],
        },
      ],
    })
  ),

  http.post(`${API_BASE_URL}/sequences`, () =>
    HttpResponse.json({ id: 'seq-new', name: 'New', ab_variant: null, is_active: true, is_global: false, steps: [], emails_sent: 0, conversions: 0, created_at: null }, { status: 201 })
  ),

  http.put(`${API_BASE_URL}/sequences/:id`, () =>
    HttpResponse.json({ id: 'seq-2', name: 'Updated', ab_variant: 'C', is_active: true, is_global: false, steps: [], emails_sent: 0, conversions: 0, created_at: null, cloned_from_global: false })
  ),

  http.delete(`${API_BASE_URL}/sequences/:id`, () =>
    HttpResponse.json({ status: 'deactivated', id: 'seq-2' })
  ),

  // ── Approvals — autonomy dial + pending queue ──────────────────────────────
  http.get(`${API_BASE_URL}/outreach/autonomy`, () =>
    HttpResponse.json({ mode: 'approve', modes: ['draft', 'approve', 'auto'], pending_count: 1 })
  ),

  http.put(`${API_BASE_URL}/outreach/autonomy`, async ({ request }) => {
    const body = (await request.json()) as { mode: string };
    return HttpResponse.json({ mode: body.mode });
  }),

  http.get(`${API_BASE_URL}/outreach/approvals`, () =>
    HttpResponse.json({
      total: 1,
      mode: 'approve',
      emails: [
        {
          id: 'em-1',
          lead_id: 'lead-1',
          lead_name: 'Alice Chen',
          lead_email: 'alice@startup.io',
          company: 'Startup IO',
          step_number: 1,
          subject: 'Quick question about Startup IO',
          body: 'Hi Alice,\n\nSaw your team is scaling…',
          quality_score: 0.87,
          claims: {
            claims: [
              {
                text: 'Saw that Startup IO raised a $12M Series A.',
                status: 'verified',
                score: 0.82,
                source_id: 'research-0-0',
                source_kind: 'web_search',
                source_title: 'Startup IO raises $12M Series A',
                source_excerpt: 'Startup IO announced a $12M Series A round led by Example Ventures.',
              },
              {
                text: 'We helped a similar company grow revenue by 300% in 6 weeks.',
                status: 'unverified',
                score: 0.1,
                source_id: null,
                source_kind: null,
                source_title: null,
                source_excerpt: null,
              },
            ],
            verified: 1,
            unverified: 1,
            grounding_score: 0.5,
            sources: [{ id: 'research-0-0', kind: 'web_search', title: 'Startup IO raises $12M Series A' }],
          },
          scheduled_at: '2026-07-03T10:00:00Z',
          created_at: '2026-07-03T09:00:00Z',
        },
      ],
    })
  ),

  http.post(`${API_BASE_URL}/outreach/approvals/:id/approve`, () =>
    HttpResponse.json({ status: 'scheduled', id: 'em-1', edited: false })
  ),

  http.post(`${API_BASE_URL}/outreach/approvals/:id/reject`, () =>
    HttpResponse.json({ status: 'rejected', id: 'em-1' })
  ),

  http.post(`${API_BASE_URL}/outreach/approvals/approve-all`, () =>
    HttpResponse.json({ approved: 1 })
  ),

  // ── Sending mailboxes ───────────────────────────────────────────────────────
  http.get(`${API_BASE_URL}/mailboxes`, () =>
    HttpResponse.json({
      total: 1,
      mailboxes: [
        {
          id: 'mb-1', email: 'rep@corp.com', display_name: 'Rep Person', provider: 'smtp',
          smtp_host: 'smtp.corp.com', imap_enabled: true, is_active: true,
          daily_limit: 50, effective_daily_limit: 25, sent_last_24h: 8, warming_up: true,
          last_used_at: '2026-07-03T09:00:00Z', last_imap_poll_at: '2026-07-03T09:30:00Z',
          created_at: '2026-06-30T00:00:00Z',
        },
      ],
    })
  ),

  http.post(`${API_BASE_URL}/mailboxes`, () =>
    HttpResponse.json({
      id: 'mb-2', email: 'new@corp.com', display_name: '', provider: 'smtp',
      smtp_host: 'smtp.corp.com', imap_enabled: false, is_active: true,
      daily_limit: 50, effective_daily_limit: 10, sent_last_24h: 0, warming_up: true,
      last_used_at: null, last_imap_poll_at: null, created_at: null,
    }, { status: 201 })
  ),

  http.post(`${API_BASE_URL}/mailboxes/:id/test`, () =>
    HttpResponse.json({ ok: true, message: 'SMTP login OK' })
  ),

  http.delete(`${API_BASE_URL}/mailboxes/:id`, () =>
    HttpResponse.json({ status: 'deactivated', id: 'mb-1' })
  ),

  // ── Compliance — guardrails + suppression list ─────────────────────────────
  http.get(`${API_BASE_URL}/outreach/guardrails`, () =>
    HttpResponse.json({
      can_send: true,
      reason: 'OK — 12/200 sent in last 24h',
      sent_last_24h: 12,
      daily_limit: 200,
      window_start_hour_utc: 8,
      window_end_hour_utc: 18,
      weekdays_only: true,
      suppression_count: 1,
    })
  ),

  http.get(`${API_BASE_URL}/suppressions`, () =>
    HttpResponse.json({
      total: 1,
      entries: [
        {
          id: 'sup-1',
          value: 'optout@corp.com',
          kind: 'email',
          source: 'unsubscribe_link',
          reason: null,
          lead_id: null,
          created_at: '2026-07-01T10:00:00Z',
        },
      ],
    })
  ),

  http.post(`${API_BASE_URL}/suppressions`, () =>
    HttpResponse.json(
      { id: 'sup-2', value: 'spam@corp.com', kind: 'email', cancelled_emails: 0 },
      { status: 201 }
    )
  ),

  http.delete(`${API_BASE_URL}/suppressions/:id`, () =>
    HttpResponse.json({ status: 'deleted', id: 'sup-1' })
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

  // ── Backtests ──────────────────────────────────────────────────────────────
  http.get(`${API_BASE_URL}/backtests`, () =>
    HttpResponse.json({
      total: 1,
      runs: [{ id: 'bt-1', filename: 'q1_deals.csv', status: 'complete', total_rows: 40, skipped_rows: 1, created_at: '2026-07-14T09:00:00Z' }],
    })
  ),

  http.get(`${API_BASE_URL}/backtests/:id`, () => HttpResponse.json(mockBacktestRun)),

  http.get(`${API_BASE_URL}/backtests/:id/records`, ({ request }) => {
    const missesOnly = new URL(request.url).searchParams.get('misses_only') === 'true';
    const records = missesOnly
      ? mockBacktestRecords.filter(
          (r) =>
            (r.predicted_verdict === 'Hot' && r.actual_outcome === 'lost') ||
            (r.predicted_verdict === 'Cold' && r.actual_outcome === 'won')
        )
      : mockBacktestRecords;
    return HttpResponse.json({ total: records.length, records });
  }),

  http.post(`${API_BASE_URL}/backtests`, () =>
    HttpResponse.json({ ...mockBacktestRun, id: 'bt-new', filename: 'upload.csv' }, { status: 201 })
  ),

  // ── Email verification ─────────────────────────────────────────────────────
  http.post(`${API_BASE_URL}/email-verification`, async ({ request }) => {
    const body = (await request.json()) as { email?: string };
    const undeliverable = body.email?.includes('dead');
    return HttpResponse.json({
      email: body.email ?? 'lead@corp.com',
      status: undeliverable ? 'undeliverable' : 'valid',
      reason: undeliverable ? 'Domain does not exist (NXDOMAIN)' : 'All checks passed',
      checks: {
        syntax: { ok: true },
        disposable: { ok: true },
        role_account: { ok: true },
        mx: { ok: !undeliverable, detail: undeliverable ? 'NXDOMAIN' : '2 MX record(s)' },
      },
      verified_at: '2026-07-14T09:00:00Z',
    });
  }),

  // ── OAuth mailboxes ────────────────────────────────────────────────────────
  http.get(`${API_BASE_URL}/mailboxes/oauth/:provider/start`, ({ params }) =>
    HttpResponse.json({
      authorize_url: `https://accounts.example.com/consent?provider=${params.provider}`,
      state: 'signed-state',
    })
  ),

  // ── Campaigns ──────────────────────────────────────────────────────────────
  http.get(`${API_BASE_URL}/campaigns/autonomy`, () =>
    HttpResponse.json({ mode: 'approve', modes: ['approve', 'auto'] })
  ),

  http.put(`${API_BASE_URL}/campaigns/autonomy`, async ({ request }) => {
    const body = (await request.json()) as { mode: string };
    return HttpResponse.json({ mode: body.mode });
  }),

  http.get(`${API_BASE_URL}/campaigns`, () =>
    HttpResponse.json({ total: 1, campaigns: [mockCampaign] })
  ),

  http.get(`${API_BASE_URL}/campaigns/:id`, () => HttpResponse.json(mockCampaign)),

  http.post(`${API_BASE_URL}/campaigns`, async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({ ...mockCampaign, id: 'camp-new', name: body.name }, { status: 201 });
  }),

  http.put(`${API_BASE_URL}/campaigns/:id`, () => HttpResponse.json(mockCampaign)),

  http.post(`${API_BASE_URL}/campaigns/:id/replan`, () =>
    HttpResponse.json(mockCampaignPlan)
  ),

  http.post(`${API_BASE_URL}/campaigns/:id/plans/:planId/approve`, () =>
    HttpResponse.json({
      execution: { succeeded: 2, failed: 0 },
      plan: { ...mockCampaignPlan, status: 'active' },
    })
  ),

  http.post(`${API_BASE_URL}/campaigns/:id/plans/:planId/reject`, () =>
    HttpResponse.json({ ...mockCampaignPlan, status: 'rejected' })
  ),

  http.get(`${API_BASE_URL}/campaigns/:id/report`, () =>
    HttpResponse.json({ report_md: '# Campaign report — Q3 push\n\n**Goal:** 12 meetings', generated: true })
  ),

  // ── Prospecting ────────────────────────────────────────────────────────────
  http.get(`${API_BASE_URL}/prospecting/runs`, () =>
    HttpResponse.json({
      total: 1,
      runs: [{
        id: 'prun-1', provider: 'synthetic', criteria: { industry: 'SaaS' },
        campaign_id: null, requested: 10, found: 12, accepted: 8,
        rejected: { suppressed: 1, duplicate: 2, undeliverable: 1, low_score: 0, budget: 0 },
        cost_usd: 0, dry_run: false, created_at: '2026-07-15T10:00:00Z',
      }],
      budget: { max_per_day: 100, accepted_today: 8 },
    })
  ),

  http.post(`${API_BASE_URL}/prospecting/runs`, async ({ request }) => {
    const body = (await request.json()) as { dry_run?: boolean; limit?: number };
    return HttpResponse.json({
      id: 'prun-new', provider: 'synthetic', criteria: { industry: 'SaaS' },
      campaign_id: null, requested: body.limit ?? 10, found: 12,
      accepted: body.dry_run ? 0 : 2,
      rejected: { suppressed: 1, duplicate: 0, undeliverable: 1, low_score: 0, budget: 0 },
      cost_usd: 0, dry_run: !!body.dry_run, created_at: '2026-07-16T10:00:00Z',
      candidates: [
        { name: 'Ava Keller', email: 'ava.keller@notion.so', company: 'Notion', job_title: 'VP of Product',
          industry: 'SaaS', company_size: '200-500', score: 0.81, verdict: 'Hot', icp_match: true, verification_status: 'valid' },
        { name: 'Hugo Berg', email: 'hugo.berg@linear.app', company: 'Linear', job_title: 'Engineering Manager',
          industry: 'DevTools', company_size: '50-200', score: 0.62, verdict: 'Warm', icp_match: true, verification_status: 'unknown' },
      ],
    }, { status: 201 });
  }),

  // ── Inbox + reply intelligence ─────────────────────────────────────────────
  http.get(`${API_BASE_URL}/inbox`, () =>
    HttpResponse.json({
      conversations: [
        {
          id: 'conv-1', lead_id: 'lead-1', lead_name: 'Alice Chen', lead_email: 'alice@startup.io',
          company: 'Startup IO', channel: 'email', message_count: 2, summary: null,
          sentiment: null,
          classification: { category: 'objection', subtype: 'competitor', confidence: 0.85, method: 'keyword', extracted: {} },
          needs_human: true, human_flagged_at: '2026-07-16T09:00:00Z', updated_at: '2026-07-16T09:00:00Z',
          messages: [{ role: 'lead', content: 'We already use Outreach and are happy with it.', timestamp: '2026-07-16T09:00:00Z' }],
        },
        {
          id: 'conv-2', lead_id: 'lead-2', lead_name: 'Bob Roe', lead_email: 'bob@shop.com',
          company: 'Shopful', channel: 'email', message_count: 1, summary: null,
          sentiment: null,
          classification: { category: 'auto_reply', subtype: null, confidence: 0.85, method: 'keyword', extracted: {} },
          needs_human: false, human_flagged_at: null, updated_at: '2026-07-16T08:00:00Z',
          messages: [{ role: 'lead', content: 'Out of office until Monday.', timestamp: '2026-07-16T08:00:00Z' }],
        },
      ],
      count: 2,
      needs_review: 1,
    })
  ),

  http.get(`${API_BASE_URL}/analytics/objections`, () =>
    HttpResponse.json({
      total_objections: 5,
      by_subtype: { competitor: 3, price: 2 },
      by_industry: { SaaS: { competitor: 2 }, FinTech: { competitor: 1, price: 2 } },
      top: [
        { subtype: 'competitor', count: 3 },
        { subtype: 'price', count: 2 },
      ],
      examples: {
        competitor: [
          { company: 'Startup IO', industry: 'SaaS', text: 'We already use Outreach and are happy with it.' },
        ],
        price: [],
      },
    })
  ),

  // ── CRM sync ───────────────────────────────────────────────────────────────
  http.get(`${API_BASE_URL}/crm/status`, () =>
    HttpResponse.json({
      hubspot: {
        oauth_configured: true, connected: true, portal_id: '12345',
        last_outbound_at: '2026-07-17T08:00:00Z', last_inbound_at: '2026-07-17T09:00:00Z',
        legacy_api_key: false,
      },
    })
  ),

  http.get(`${API_BASE_URL}/crm/log`, () =>
    HttpResponse.json({
      entries: [
        { direction: 'inbound', event_type: 'contact.lifecyclestage', lead_id: 'lead-1',
          external_id: '901', payload: { value: 'customer', applied: true }, success: true,
          error_message: null, created_at: '2026-07-17T09:00:00Z' },
        { direction: 'outbound', event_type: 'contact.created', lead_id: 'lead-1',
          external_id: '901', payload: { verdict: 'Hot' }, success: true,
          error_message: null, created_at: '2026-07-17T08:00:00Z' },
      ],
    })
  ),

  http.get(`${API_BASE_URL}/crm/hubspot/start`, () =>
    HttpResponse.json({
      authorize_url: 'https://app.hubspot.com/oauth/authorize?client_id=x',
      state: 'signed-state',
    })
  ),

  http.delete(`${API_BASE_URL}/crm/hubspot`, () =>
    HttpResponse.json({ status: 'disconnected' })
  ),

  // ── Health ─────────────────────────────────────────────────────────────────
  http.get(`${API_BASE_URL}/health`, () =>
    HttpResponse.json({ status: 'healthy', service: 'autonomous-sdr', version: '1.0.0', worker_active: true, worker_last_seen: new Date().toISOString() })
  ),
];

// ── Campaign mock data ───────────────────────────────────────────────────────

export const mockCampaignPlan = {
  id: 'plan-1',
  version: 2,
  status: 'pending_approval',
  generated_at: '2026-07-15T08:00:00Z',
  diagnosis: 'Behind pace: reply rate in the SaaS segment dropped to 1.1% and variant A is dragging.',
  actions: [
    { type: 'pause_sequence', sequence_id: 'seq-a', reason: '0.4% reply rate over 60 sends' },
    { type: 'create_variant', angle: 'lead with the displacement objection', draft_steps: [{ step: 1, delay_days: 0, subject_template: 's', body_template: 'b' }] },
    { type: 'escalate', severity: 'warning', message: 'Pipeline coverage below 2x remaining goal' },
  ],
  approved_at: null,
  rejection_reason: null,
};

export const mockCampaign = {
  id: 'camp-1',
  name: 'Q3 meetings push',
  goal_type: 'meetings',
  goal_target: 12,
  period_start: '2026-07-06T00:00:00',
  period_end: '2026-07-17T23:59:59',
  status: 'active',
  constraints: { max_daily_sends: 50, segments: [{ industry: 'SaaS' }] },
  created_at: '2026-07-06T09:00:00Z',
  pace: {
    expected_by_now: 5.0, actual: 3, pace_ratio: 0.6,
    projected_end_total: 6, elapsed_weekdays: 5, total_weekdays: 10,
  },
  progress: {
    goal_actual: 3,
    total: { leads: 40, sends: 120, replies: 6, bounces: 2, bounce_rate: 0.0167, meetings: 3, qualified: 14, spend_usd: 1.24 },
    segments: [],
  },
  current_plan: mockCampaignPlan,
};

// ── Backtest mock data ───────────────────────────────────────────────────────

export const mockBacktestRun = {
  id: 'bt-1',
  filename: 'q1_deals.csv',
  status: 'complete',
  total_rows: 40,
  skipped_rows: 1,
  created_at: '2026-07-14T09:00:00Z',
  errors: 'Row 12: unrecognised outcome "maybe"',
  summary: {
    total: 40,
    won: 10,
    lost: 30,
    base_win_rate: 0.25,
    verdict_outcome_matrix: {
      Hot: { won: 8, lost: 4 },
      Warm: { won: 2, lost: 10 },
      Cold: { won: 0, lost: 16 },
    },
    hot_recall: 0.8,
    hot_or_warm_recall: 1.0,
    hot_precision: 0.667,
    hot_lift: 2.67,
    calibration: [
      { range: [0, 0.2], count: 6, mean_predicted_score: 0.15, actual_win_rate: 0 },
      { range: [0.2, 0.4], count: 10, mean_predicted_score: 0.32, actual_win_rate: 0.1 },
      { range: [0.4, 0.6], count: 12, mean_predicted_score: 0.51, actual_win_rate: 0.17 },
      { range: [0.6, 0.8], count: 8, mean_predicted_score: 0.7, actual_win_rate: 0.5 },
      { range: [0.8, 1.0], count: 4, mean_predicted_score: 0.86, actual_win_rate: 0.75 },
    ],
  },
};

export const mockBacktestRecords = [
  {
    row_number: 2,
    name: 'Jane Doe',
    email: 'jane@acme.io',
    company: 'Acme',
    actual_outcome: 'won',
    predicted_verdict: 'Hot',
    predicted_score: 0.85,
    icp_match: true,
    features: { bant: { budget: 0.75, authority: 0.85, need: 0.9, timeline: 0.65 }, defaulted: [], guardrail_flag: null, headcount: 350, seniority: 'VP' },
    reasoning: 'BANT 0.85',
  },
  {
    row_number: 3,
    name: 'Bob Roe',
    email: 'bob@shop.com',
    company: 'Shopful',
    actual_outcome: 'lost',
    predicted_verdict: 'Hot',
    predicted_score: 0.78,
    icp_match: false,
    features: { bant: { budget: 0.9, authority: 0.85, need: 0.5, timeline: 0.65 }, defaulted: ['need'], guardrail_flag: null, headcount: 900, seniority: 'C-Suite' },
    reasoning: 'BANT 0.78; defaulted: need',
  },
  {
    row_number: 4,
    name: 'Ann Lee',
    email: 'ann@beta.dev',
    company: 'Beta Dev',
    actual_outcome: 'lost',
    predicted_verdict: 'Cold',
    predicted_score: 0.3,
    icp_match: false,
    features: { bant: { budget: 0.4, authority: 0.15, need: 0.3, timeline: 0.8 }, defaulted: [], guardrail_flag: 'authority_and_need_both_low', headcount: 30, seniority: 'Junior' },
    reasoning: 'BANT 0.30; guardrail: authority_and_need_both_low',
  },
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
