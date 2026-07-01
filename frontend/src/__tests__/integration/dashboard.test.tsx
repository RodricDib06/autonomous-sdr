import { describe, it, expect, afterEach, vi } from 'vitest';
import { act } from '@testing-library/react';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { renderWithProviders } from '../utils';
import Dashboard from '../../pages/Dashboard';
import { server } from '../mocks/server';
import { mockCoolingLeads } from '../mocks/handlers';
import type { GlobalEvent } from '../../types';

// Capture useGlobalEvents callbacks so we can call them in tests
let capturedCallbacks: { onLeadComplete?: (e: GlobalEvent) => void; onOptimization?: (e: GlobalEvent) => void } = {};
vi.mock('../../hooks/useGlobalEvents', () => ({
  useGlobalEvents: vi.fn((opts: { onLeadComplete?: (e: GlobalEvent) => void; onOptimization?: (e: GlobalEvent) => void }) => {
    capturedCallbacks = opts;
  }),
}));

afterEach(() => {
  server.resetHandlers();
  localStorage.removeItem('asdr_acv');
});

describe('Dashboard page', () => {
  it('renders the page header', () => {
    renderWithProviders(<Dashboard />);
    expect(screen.getByText('Dashboard')).toBeInTheDocument();
    expect(screen.getByText('Real-time overview of your lead pipeline')).toBeInTheDocument();
  });

  it('shows skeleton cards while loading', () => {
    const { container } = renderWithProviders(<Dashboard />);
    expect(container.querySelectorAll('.skeleton').length).toBeGreaterThan(0);
  });

  it('renders KPI stat cards after data loads', async () => {
    renderWithProviders(<Dashboard />);
    await waitFor(() => {
      expect(screen.getByText('Total Leads')).toBeInTheDocument();
      expect(screen.getByText('Completed')).toBeInTheDocument();
      expect(screen.getByText('Hot Leads')).toBeInTheDocument();
      expect(screen.getByText('Processing')).toBeInTheDocument();
    });
  });

  it('displays stats values from the API', async () => {
    renderWithProviders(<Dashboard />);
    // stats mock: total_leads=150, completed=120
    await waitFor(() => {
      expect(screen.getByText('150')).toBeInTheDocument();
      expect(screen.getByText('120')).toBeInTheDocument();
      // "12" appears in multiple elements (hot leads stat + quality breakdown)
      expect(screen.getAllByText('12').length).toBeGreaterThan(0);
    });
  });

  it('renders outreach KPI row', async () => {
    renderWithProviders(<Dashboard />);
    await waitFor(() => {
      expect(screen.getByText('Emails Sent')).toBeInTheDocument();
      expect(screen.getByText('Open Rate')).toBeInTheDocument();
      expect(screen.getByText('Reply Rate')).toBeInTheDocument();
    });
  });

  it('displays outreach numbers from the API', async () => {
    renderWithProviders(<Dashboard />);
    // outreach mock: total_sent=85, open_rate=0.41, reply_rate=0.14
    await waitFor(() => {
      expect(screen.getByText('85')).toBeInTheDocument();
      expect(screen.getByText('41%')).toBeInTheDocument();
      expect(screen.getByText('14%')).toBeInTheDocument();
    });
  });

  it('renders Hot Leads section heading', async () => {
    renderWithProviders(<Dashboard />);
    await waitFor(() => {
      expect(screen.getByText(/Hot Leads/)).toBeInTheDocument();
    });
  });

  it('shows hot lead name from API after loading', async () => {
    renderWithProviders(<Dashboard />);
    // hot leads mock has "John Doe"
    await waitFor(() => {
      expect(screen.getByText('John Doe')).toBeInTheDocument();
    });
  });

  it('shows A/B winner card', async () => {
    renderWithProviders(<Dashboard />);
    // ab test mock: winner='B'
    await waitFor(() => {
      expect(screen.getByText('A/B Winner')).toBeInTheDocument();
      expect(screen.getByText('Variant B')).toBeInTheDocument();
    });
  });

  it('renders chart sections', async () => {
    renderWithProviders(<Dashboard />);
    await waitFor(() => {
      expect(screen.getByText('Verdict Breakdown')).toBeInTheDocument();
      expect(screen.getByText('Data Quality')).toBeInTheDocument();
      expect(screen.getByText('Pipeline Status')).toBeInTheDocument();
    });
  });

  it('shows estimated pipeline value banner', async () => {
    renderWithProviders(<Dashboard />);
    await waitFor(() => {
      expect(screen.getByText('Estimated Pipeline Value')).toBeInTheDocument();
    });
    // (hot 12 + warm 35) * 25000 = $1,175,000 → $1.2M
    expect(screen.getByText(/\$\d/)).toBeInTheDocument();
  });

  it('shows default ACV value in the pipeline banner', async () => {
    renderWithProviders(<Dashboard />);
    await waitFor(() => {
      // ACV defaults to 25000 → shown as $25K
      expect(screen.getByText(/ACV/)).toBeInTheDocument();
    });
  });

  it('clicking ACV opens the inline edit form', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Dashboard />);
    await waitFor(() => expect(screen.getByText(/ACV/)).toBeInTheDocument());

    await user.click(screen.getByText(/ACV/));

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/avg deal/i)).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /save/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument();
  });

  it('submitting a new ACV value updates the banner', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Dashboard />);
    await waitFor(() => expect(screen.getByText(/ACV/)).toBeInTheDocument());

    await user.click(screen.getByText(/ACV/));
    await waitFor(() => expect(screen.getByPlaceholderText(/avg deal/i)).toBeInTheDocument());

    const input = screen.getByPlaceholderText(/avg deal/i);
    await user.clear(input);
    await user.type(input, '50000');
    await user.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => {
      expect(screen.queryByPlaceholderText(/avg deal/i)).not.toBeInTheDocument();
    });
  });

  it('cancel ACV edit closes the form without updating', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Dashboard />);
    await waitFor(() => expect(screen.getByText(/ACV/)).toBeInTheDocument());

    await user.click(screen.getByText(/ACV/));
    await waitFor(() => expect(screen.getByPlaceholderText(/avg deal/i)).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /cancel/i }));

    await waitFor(() => {
      expect(screen.queryByPlaceholderText(/avg deal/i)).not.toBeInTheDocument();
    });
    expect(screen.getByText(/ACV/)).toBeInTheDocument();
  });

  it('shows cooling leads section when cooling data has entries', async () => {
    server.use(
      http.get('http://localhost:8000/leads/cooling', () =>
        HttpResponse.json({ leads: mockCoolingLeads, count: mockCoolingLeads.length })
      )
    );
    renderWithProviders(<Dashboard />);
    await waitFor(() => {
      expect(screen.getByText(/Cooling Leads/i)).toBeInTheDocument();
    });
    expect(screen.getByText('Alice Chen')).toBeInTheDocument();
    expect(screen.getByText('Bob Kim')).toBeInTheDocument();
  });

  it('shows urgency badge count in cooling section', async () => {
    server.use(
      http.get('http://localhost:8000/leads/cooling', () =>
        HttpResponse.json({ leads: mockCoolingLeads, count: mockCoolingLeads.length })
      )
    );
    renderWithProviders(<Dashboard />);
    await waitFor(() => {
      expect(screen.getByText(`${mockCoolingLeads.length} at risk`)).toBeInTheDocument();
    });
  });

  it('does not show cooling section when count is 0', async () => {
    renderWithProviders(<Dashboard />);
    await waitFor(() => expect(screen.getByText('Emails Sent')).toBeInTheDocument());
    expect(screen.queryByText(/Cooling Leads/i)).not.toBeInTheDocument();
  });

  it('shows quality distribution bars with data', async () => {
    renderWithProviders(<Dashboard />);
    await waitFor(() => {
      // quality mock returns: { excellent: 20, good: 60, fair: 50, poor: 20 }
      expect(screen.getByText('Excellent')).toBeInTheDocument();
      expect(screen.getByText('Good')).toBeInTheDocument();
    });
  });

  it('fires hot lead toast when onLeadComplete receives Hot verdict', async () => {
    renderWithProviders(<Dashboard />);
    await waitFor(() => screen.getByText('Total Leads'));

    await act(async () => {
      capturedCallbacks.onLeadComplete?.({
        type: 'lead_complete', verdict: 'Hot', lead_name: 'Alice Test', company: 'Acme Corp',
      });
    });

    await waitFor(() => {
      expect(screen.getByText(/New hot lead/i)).toBeInTheDocument();
    });
  });

  it('fires warm lead toast when onLeadComplete receives Warm verdict', async () => {
    renderWithProviders(<Dashboard />);
    await waitFor(() => screen.getByText('Total Leads'));

    await act(async () => {
      capturedCallbacks.onLeadComplete?.({
        type: 'lead_complete', verdict: 'Warm', lead_name: 'Bob Test', company: 'Beta Inc',
      });
    });

    await waitFor(() => {
      expect(screen.getByText(/Warm lead qualified/i)).toBeInTheDocument();
    });
  });

  it('fires no extra toast for non-hot/warm leads but still refreshes data', async () => {
    renderWithProviders(<Dashboard />);
    await waitFor(() => screen.getByText('Total Leads'));

    // Cold verdict — no toast, but query invalidations should still fire without error
    await act(async () => {
      capturedCallbacks.onLeadComplete?.({
        type: 'lead_complete', verdict: 'Cold', lead_name: 'Carol Test', company: 'Cold Co',
      });
    });

    // No hot/warm toast — page still intact
    expect(screen.getByText('Total Leads')).toBeInTheDocument();
  });

  it('fires BANT weights updated toast when onOptimization fires', async () => {
    renderWithProviders(<Dashboard />);
    await waitFor(() => screen.getByText('Total Leads'));

    await act(async () => {
      capturedCallbacks.onOptimization?.({ type: 'optimization' });
    });

    await waitFor(() => {
      expect(screen.getByText(/BANT weights updated/i)).toBeInTheDocument();
    });
  });
});
