import { describe, it, expect, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { renderWithProviders } from '../utils';
import Approvals from '../../pages/Approvals';
import { useAuthStore } from '../../store/authStore';
import { mockUser } from '../mocks/handlers';
import { server } from '../mocks/server';

beforeEach(() => {
  useAuthStore.setState({ user: mockUser, accessToken: 'tok', refreshToken: 'ref' });
});

describe('Approvals page', () => {
  it('renders the autonomy dial with current mode highlighted', async () => {
    renderWithProviders(<Approvals />);
    await waitFor(() => {
      expect(screen.getAllByText('Approve first').length).toBeGreaterThan(0);
    });
    expect(screen.getByText('Full auto')).toBeInTheDocument();
    expect(screen.getByText('Draft only')).toBeInTheDocument();
  });

  it('lists pending emails with lead context', async () => {
    renderWithProviders(<Approvals />);
    await waitFor(() => {
      expect(screen.getByText('Alice Chen')).toBeInTheDocument();
    });
    expect(screen.getByText('Quick question about Startup IO')).toBeInTheDocument();
    expect(screen.getByText('quality 87')).toBeInTheDocument();
  });

  it('approves an email and shows a success toast', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Approvals />);
    await waitFor(() => screen.getByText('Alice Chen'));

    await user.click(screen.getByRole('button', { name: /approve & send/i }));
    await waitFor(() => {
      expect(screen.getByText(/will send on the next scheduler tick/i)).toBeInTheDocument();
    });
  });

  it('lets the reviewer edit before approving', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Approvals />);
    await waitFor(() => screen.getByText('Alice Chen'));

    await user.click(screen.getByRole('button', { name: /^edit$/i }));
    const subjectInput = screen.getByLabelText('Email subject');
    expect(subjectInput).toHaveValue('Quick question about Startup IO');
    expect(screen.getByRole('button', { name: /approve with edits/i })).toBeInTheDocument();
  });

  it('shows empty state when queue is clear', async () => {
    server.use(
      http.get('http://localhost:8000/outreach/approvals', () =>
        HttpResponse.json({ total: 0, mode: 'approve', emails: [] })
      )
    );
    renderWithProviders(<Approvals />);
    await waitFor(() => {
      expect(screen.getByText('Queue is clear')).toBeInTheDocument();
    });
  });

  it('shows approve-all for managers when queue is non-empty', async () => {
    useAuthStore.setState({ user: { ...mockUser, role: 'manager' }, accessToken: 'tok', refreshToken: 'ref' });
    renderWithProviders(<Approvals />);
    await waitFor(() => screen.getByText('Alice Chen'));
    expect(screen.getByRole('button', { name: /approve all/i })).toBeInTheDocument();
  });
});

describe('Approvals — provenance fact check', () => {
  it('flags drafts with unverified claims in the header badge', async () => {
    renderWithProviders(<Approvals />);
    await waitFor(() => screen.getByText('Alice Chen'));
    expect(screen.getByText(/1 unverified claim/i)).toBeInTheDocument();
  });

  it('opens the fact-check panel by default when a claim is unsupported', async () => {
    renderWithProviders(<Approvals />);
    await waitFor(() => screen.getByText('Alice Chen'));

    expect(screen.getByText('Fact check')).toBeInTheDocument();
    expect(screen.getByText(/1\/2 claims traced to a source/i)).toBeInTheDocument();
    // The invented metric is called out with remediation guidance
    expect(screen.getByText(/grow revenue by 300% in 6 weeks/i)).toBeInTheDocument();
    expect(screen.getByText(/no supporting source found/i)).toBeInTheDocument();
  });

  it('reveals the supporting source excerpt on click', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Approvals />);
    await waitFor(() => screen.getByText('Alice Chen'));

    await user.click(screen.getByRole('button', { name: /web search .* raises \$12m series a/i }));
    expect(
      screen.getByText(/announced a \$12M Series A round led by Example Ventures/i)
    ).toBeInTheDocument();
  });

  it('shows an all-sourced badge and a collapsed panel when every claim verifies', async () => {
    server.use(
      http.get('http://localhost:8000/outreach/approvals', () =>
        HttpResponse.json({
          total: 1,
          mode: 'approve',
          emails: [
            {
              id: 'em-2', lead_id: 'lead-1', lead_name: 'Alice Chen',
              lead_email: 'alice@startup.io', company: 'Startup IO', step_number: 1,
              subject: 's', body: 'b', quality_score: 0.9,
              claims: {
                claims: [
                  {
                    text: 'Startup IO is in the SaaS industry.', status: 'verified', score: 0.9,
                    source_id: 'enrichment', source_kind: 'enrichment',
                    source_title: 'Enrichment (domain_heuristics_v1)', source_excerpt: 'industry SaaS',
                  },
                ],
                verified: 1, unverified: 0, grounding_score: 1.0,
                sources: [{ id: 'enrichment', kind: 'enrichment', title: 'Enrichment' }],
              },
              scheduled_at: null, created_at: null,
            },
          ],
        })
      )
    );
    renderWithProviders(<Approvals />);
    await waitFor(() => screen.getByText('Alice Chen'));

    expect(screen.getByText(/all claims sourced/i)).toBeInTheDocument();
    // Collapsed by default — the claim text is not rendered until expanded
    expect(screen.queryByText('Startup IO is in the SaaS industry.')).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /fact check/i }));
    expect(screen.getByText('Startup IO is in the SaaS industry.')).toBeInTheDocument();
  });

  it('renders no fact-check panel for emails without claims', async () => {
    server.use(
      http.get('http://localhost:8000/outreach/approvals', () =>
        HttpResponse.json({
          total: 1,
          mode: 'approve',
          emails: [
            {
              id: 'em-3', lead_id: 'lead-1', lead_name: 'Alice Chen',
              lead_email: 'alice@startup.io', company: 'Startup IO', step_number: 1,
              subject: 's', body: 'b', quality_score: 0.9, claims: null,
              scheduled_at: null, created_at: null,
            },
          ],
        })
      )
    );
    renderWithProviders(<Approvals />);
    await waitFor(() => screen.getByText('Alice Chen'));
    expect(screen.queryByText('Fact check')).not.toBeInTheDocument();
  });
});
