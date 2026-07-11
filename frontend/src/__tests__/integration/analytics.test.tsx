import { describe, it, expect, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { renderWithProviders } from '../utils';
import Analytics from '../../pages/Analytics';
import { server } from '../mocks/server';

afterEach(() => {
  server.resetHandlers();
});

describe('Analytics page', () => {
  it('renders the page header', () => {
    renderWithProviders(<Analytics />);
    expect(screen.getByText('Analytics')).toBeInTheDocument();
  });

  it('renders the page subtitle', () => {
    renderWithProviders(<Analytics />);
    expect(screen.getByText('Pipeline metrics and lead intelligence')).toBeInTheDocument();
  });

  it('shows summary pill labels', async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText('Success Rate')).toBeInTheDocument();
      expect(screen.getByText('Hot Rate')).toBeInTheDocument();
      expect(screen.getByText('Avg Quality')).toBeInTheDocument();
      expect(screen.getByText('Avg Completeness')).toBeInTheDocument();
    });
  });

  it('shows computed success rate from mock data', async () => {
    renderWithProviders(<Analytics />);
    // stats mock: success_rate = 0.8 → 80%
    await waitFor(() => {
      expect(screen.getByText('80%')).toBeInTheDocument();
    });
  });

  it('renders Lead Intake Trend chart section', async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText('Lead Intake — Last 30 Days')).toBeInTheDocument();
    });
  });

  it('shows trend chart when trend data is available', async () => {
    renderWithProviders(<Analytics />);
    // Mock returns trend data — the AreaChart renders
    await waitFor(() => {
      expect(screen.getByText('Lead Intake — Last 30 Days')).toBeInTheDocument();
    });
    // Chart section renders (not empty state)
    await waitFor(() => {
      expect(screen.queryByText(/No lead data yet/i)).not.toBeInTheDocument();
    });
  });

  it('shows empty trend state when no trend data', async () => {
    server.use(
      http.get('http://localhost:8000/leads/trend', () =>
        HttpResponse.json({ data: [], days: 30 })
      )
    );
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText(/No lead data yet/i)).toBeInTheDocument();
    });
  });

  it('renders Verdict Distribution chart section', async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText('Verdict Distribution')).toBeInTheDocument();
    });
  });

  it('renders Pipeline Overview section', async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText('Pipeline Overview')).toBeInTheDocument();
    });
  });

  it('renders Outreach Funnel section', async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText('Outreach Funnel')).toBeInTheDocument();
    });
  });

  it('shows outreach funnel chart when data exists', async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      // outreach stats has total_sent: 85 — chart renders (not empty state)
      expect(screen.queryByText(/No outreach data yet/i)).not.toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByText('Open rate')).toBeInTheDocument();
      expect(screen.getByText('Reply rate')).toBeInTheDocument();
    });
  });

  it('shows outreach empty state when no data sent', async () => {
    server.use(
      http.get('http://localhost:8000/outreach/stats', () =>
        HttpResponse.json({
          total_sent: 0, total_opened: 0, total_replied: 0,
          open_rate: 0, reply_rate: 0,
          emails_by_status: { scheduled: 0, sent: 0, opened: 0, replied: 0, failed: 0 },
        })
      )
    );
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText(/No outreach data yet/i)).toBeInTheDocument();
    });
  });

  it('renders BANT Weights section', async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText('BANT Weight Evolution')).toBeInTheDocument();
    });
  });

  it('shows single-run BANT bar chart when one optimization run exists', async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      // With 1 opt run, singleWeightsData has entries — bar chart shows
      // "Evolution chart unlocks after 2+ optimization runs" message
      expect(screen.getByText(/Evolution chart unlocks after 2\+/i)).toBeInTheDocument();
    });
  });

  it('shows BANT line chart when 2+ optimization runs exist', async () => {
    server.use(
      http.get('http://localhost:8000/optimization/history', () =>
        HttpResponse.json({
          runs: [
            {
              id: 'opt-1', created_at: '2024-01-10T00:00:00Z', leads_analysed: 120,
              old_weights: { budget: 0.25, authority: 0.25, need: 0.25, timeline: 0.25 },
              new_weights: { budget: 0.3, authority: 0.2, need: 0.35, timeline: 0.15 },
              weight_delta: { budget: 0.05, authority: -0.05, need: 0.1, timeline: -0.1 },
              notes: null,
            },
            {
              id: 'opt-2', created_at: '2024-01-12T00:00:00Z', leads_analysed: 150,
              old_weights: { budget: 0.3, authority: 0.2, need: 0.35, timeline: 0.15 },
              new_weights: { budget: 0.32, authority: 0.18, need: 0.38, timeline: 0.12 },
              weight_delta: { budget: 0.02, authority: -0.02, need: 0.03, timeline: -0.03 },
              notes: null,
            },
          ],
          count: 2,
        })
      )
    );
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      // 2 runs → weightsEvolution.length > 1 → LineChart with "2 optimization runs"
      expect(screen.getByText(/2 optimization runs/i)).toBeInTheDocument();
    });
  });

  it('shows empty BANT state when no optimization runs', async () => {
    server.use(
      http.get('http://localhost:8000/optimization/history', () =>
        HttpResponse.json({ runs: [], count: 0 })
      )
    );
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText(/No optimization runs yet/i)).toBeInTheDocument();
    });
  });

  it('shows Top Industries section with data', async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText('Top Industries')).toBeInTheDocument();
    });
    // mockHotLeads has industry: 'Technology' → chart renders
    await waitFor(() => {
      expect(screen.queryByText(/No enriched leads yet/i)).not.toBeInTheDocument();
    });
  });

  it('shows empty industry state when hot leads have no industry', async () => {
    server.use(
      http.get('http://localhost:8000/leads/hot', () =>
        HttpResponse.json({ hot_leads: [{ id: 'lead-x', name: 'X', email: 'x@x.com', company: 'X', confidence: 0.9 }], count: 1 })
      )
    );
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      // No industry field → industryData empty → shows empty state
      expect(screen.getAllByText(/No enriched leads yet/i).length).toBeGreaterThan(0);
    });
  });

  it('renders Market Intelligence section with data', async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText('Market Intelligence')).toBeInTheDocument();
    });
  });

  it('shows market intelligence segment rows', async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText('Technology')).toBeInTheDocument();
      expect(screen.getByText('FinTech')).toBeInTheDocument();
    });
  });

  it('market intel shows lift and hot rate columns', async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText('Hot rate')).toBeInTheDocument();
      expect(screen.getByText('Lift')).toBeInTheDocument();
    });
  });

  it('market intel does not render when segments is empty', async () => {
    server.use(
      http.get('http://localhost:8000/analytics/market-intelligence', () =>
        HttpResponse.json({
          segments: [],
          top_industries: [],
          global_stats: { total: 0, hot: 0, warm: 0, cold: 0, global_hot_rate: 0 },
          computed_at: '2024-01-15T12:00:00Z',
        })
      )
    );
    renderWithProviders(<Analytics />);
    // Give time for queries to settle
    await waitFor(() => {
      expect(screen.queryByText('Market Intelligence')).not.toBeInTheDocument();
    });
  });

  it('shows quality distribution section title', async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText('Data Quality Distribution')).toBeInTheDocument();
    });
  });

  it('shows seniority breakdown section', async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText('Seniority Breakdown')).toBeInTheDocument();
    });
  });
});

describe('Analytics — ROI panel', () => {
  it('shows unit economics computed from pipeline data', async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText('ROI — AI vs human SDR')).toBeInTheDocument();
    });
    expect(screen.getByText('Cost per qualified lead')).toBeInTheDocument();
    expect(screen.getByText('$0.028')).toBeInTheDocument();
    expect(screen.getByText('Projected annual savings')).toBeInTheDocument();
    expect(screen.getByText('$15,191')).toBeInTheDocument();
  });
});
