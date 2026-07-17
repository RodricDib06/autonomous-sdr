import { describe, it, expect, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { renderWithProviders } from '../utils';
import Campaigns from '../../pages/Campaigns';
import { useAuthStore } from '../../store/authStore';
import { mockUser, mockCampaign } from '../mocks/handlers';
import { server } from '../mocks/server';

beforeEach(() => {
  useAuthStore.setState({
    user: { ...mockUser, role: 'manager' },
    accessToken: 'tok',
    refreshToken: 'ref',
  });
});

describe('Campaigns page', () => {
  it('shows the strategy autonomy dial defaulting to approve', async () => {
    renderWithProviders(<Campaigns />);
    await waitFor(() => {
      expect(screen.getByText('Strategy autonomy')).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /approve plans/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /full auto/i })).toBeInTheDocument();
  });

  it('renders the campaign with goal progress and pace', async () => {
    renderWithProviders(<Campaigns />);
    await waitFor(() => screen.getByText('Q3 meetings push'));

    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText(/\/ 12 meetings booked/)).toBeInTheDocument();
    expect(screen.getByText(/pace ×0\.6/)).toBeInTheDocument();
    expect(screen.getByText(/projected 6 by/i)).toBeInTheDocument();
    expect(screen.getByText(/5\/10 working days elapsed/i)).toBeInTheDocument();
  });

  it('renders the pending agent plan with human-readable actions', async () => {
    renderWithProviders(<Campaigns />);
    await waitFor(() => screen.getByText(/agent plan v2/i));

    expect(screen.getByText(/behind pace: reply rate in the saas segment/i)).toBeInTheDocument();
    expect(screen.getByText(/pause sequence — 0\.4% reply rate over 60 sends/i)).toBeInTheDocument();
    expect(screen.getByText(/new variant: lead with the displacement objection/i)).toBeInTheDocument();
    expect(screen.getByText(/escalate \(warning\)/i)).toBeInTheDocument();
  });

  it('approves a plan and reports execution', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Campaigns />);
    await waitFor(() => screen.getByText(/agent plan v2/i));

    await user.click(screen.getByRole('button', { name: /approve & execute/i }));
    await waitFor(() => {
      expect(screen.getByText(/plan applied — 2 action\(s\) executed/i)).toBeInTheDocument();
    });
  });

  it('triggers a manual replan', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Campaigns />);
    await waitFor(() => screen.getByText('Q3 meetings push'));

    await user.click(screen.getByRole('button', { name: /replan now/i }));
    await waitFor(() => {
      expect(screen.getByText(/agent produced a fresh plan/i)).toBeInTheDocument();
    });
  });

  it('opens the agent report dialog', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Campaigns />);
    await waitFor(() => screen.getByText('Q3 meetings push'));

    await user.click(screen.getByRole('button', { name: /agent report/i }));
    await waitFor(() => {
      expect(screen.getByText(/campaign report — q3 push/i)).toBeInTheDocument();
    });
  });

  it('creates a campaign through the dialog', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Campaigns />);
    await waitFor(() => screen.getByText('Strategy autonomy'));

    await user.click(screen.getByRole('button', { name: /new campaign/i }));
    await user.type(screen.getByPlaceholderText('Q3 meetings push'), 'Autumn pipeline build');
    await user.type(screen.getByLabelText('Period start'), '2026-08-03');
    await user.type(screen.getByLabelText('Period end'), '2026-08-28');
    await user.click(screen.getByRole('button', { name: /create campaign/i }));

    await waitFor(() => {
      expect(screen.getByText(/"autumn pipeline build" created/i)).toBeInTheDocument();
    });
  });

  it('hides manager controls from reps', async () => {
    useAuthStore.setState({ user: mockUser, accessToken: 'tok', refreshToken: 'ref' }); // rep
    renderWithProviders(<Campaigns />);
    await waitFor(() => screen.getByText('Q3 meetings push'));

    expect(screen.queryByRole('button', { name: /new campaign/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /approve & execute/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /replan now/i })).not.toBeInTheDocument();
  });

  it('shows the empty state when no campaigns exist', async () => {
    server.use(
      http.get('http://localhost:8000/campaigns', () =>
        HttpResponse.json({ total: 0, campaigns: [] })
      )
    );
    renderWithProviders(<Campaigns />);
    await waitFor(() => {
      expect(screen.getByText('No campaigns yet')).toBeInTheDocument();
    });
  });

  it('marks an executed plan with per-action results', async () => {
    const executed = {
      ...mockCampaign,
      current_plan: {
        ...mockCampaign.current_plan,
        status: 'active',
        actions: [{ type: 'escalate', severity: 'info', message: 'on track' }],
        execution_log: [{ action_type: 'escalate', success: true, error_message: null, executed_at: '2026-07-15T09:00:00Z', result: {} }],
      },
    };
    server.use(
      http.get('http://localhost:8000/campaigns', () =>
        HttpResponse.json({ total: 1, campaigns: [executed] })
      ),
      http.get('http://localhost:8000/campaigns/camp-1', () => HttpResponse.json(executed))
    );
    renderWithProviders(<Campaigns />);
    await waitFor(() => screen.getByText(/agent plan v2/i));
    await waitFor(() => {
      expect(screen.getByLabelText('Executed')).toBeInTheDocument();
    });
  });
});
