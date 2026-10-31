import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { renderWithProviders } from '../utils';
import Inbox from '../../pages/Inbox';
import Analytics from '../../pages/Analytics';
import { useAuthStore } from '../../store/authStore';
import { mockUser } from '../mocks/handlers';
import { server } from '../mocks/server';

beforeEach(() => {
  // happy-dom doesn't implement scrollIntoView (Inbox auto-scrolls the thread)
  Element.prototype.scrollIntoView = vi.fn();
  useAuthStore.setState({
    user: { ...mockUser, role: 'manager' },
    accessToken: 'tok',
    refreshToken: 'ref',
  });
});

describe('Inbox — reply classification chips', () => {
  it('shows the objection subtype on the conversation row', async () => {
    renderWithProviders(<Inbox />);
    await waitFor(() => screen.getByText('Alice Chen'));
    expect(screen.getByText(/objection: competitor/i)).toBeInTheDocument();
  });

  it('marks autoresponders distinctly', async () => {
    renderWithProviders(<Inbox />);
    await waitFor(() => screen.getByText('Bob Roe'));
    expect(screen.getByText(/auto-reply/i)).toBeInTheDocument();
  });

  it('explains the classification method on hover', async () => {
    renderWithProviders(<Inbox />);
    await waitFor(() => screen.getByText('Alice Chen'));
    const chip = screen.getByText(/objection: competitor/i);
    expect(chip).toHaveAttribute('title', expect.stringMatching(/keyword.*85%/i));
  });
});

describe('Inbox — agent drafts', () => {
  it('labels an agent email reply that was never sent', async () => {
    server.use(
      http.get('http://localhost:8000/inbox', () =>
        HttpResponse.json({
          conversations: [{
            id: 'conv-9', lead_id: 'lead-9', lead_name: 'Dana Fox', lead_email: 'dana@fox.io',
            company: 'Fox', channel: 'email', message_count: 2, summary: null, sentiment: null,
            classification: null, needs_human: false, human_flagged_at: null,
            updated_at: '2026-07-16T09:00:00Z',
            messages: [
              { role: 'lead', content: 'Can you send pricing?', timestamp: '2026-07-16T09:00:00Z' },
              { role: 'agent', content: 'Sure — attached.', timestamp: '2026-07-16T09:01:00Z', delivered: false },
            ],
          }],
          count: 1,
          needs_review: 0,
        })
      )
    );
    renderWithProviders(<Inbox />);
    await waitFor(() => screen.getByText('Sure — attached.'));
    expect(screen.getByText(/Draft — not sent/)).toBeInTheDocument();
  });
});

describe('Analytics — objections panel', () => {
  it('renders the top objections with counts and a real example quote', async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText('What prospects push back with')).toBeInTheDocument();
    });
    expect(screen.getByText('Existing vendor')).toBeInTheDocument();
    expect(screen.getByText('Price / budget')).toBeInTheDocument();
    expect(screen.getByText(/we already use outreach and are happy with it/i)).toBeInTheDocument();
    expect(screen.getByText(/— Startup IO \(SaaS\)/i)).toBeInTheDocument();
  });

  it('hides the panel entirely when there are no objections yet', async () => {
    server.use(
      http.get('http://localhost:8000/analytics/objections', () =>
        HttpResponse.json({ total_objections: 0, by_subtype: {}, by_industry: {}, top: [], examples: {} })
      )
    );
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      // another panel proves the page rendered
      expect(screen.getByText(/roi — ai vs human sdr/i)).toBeInTheDocument();
    });
    expect(screen.queryByText('What prospects push back with')).not.toBeInTheDocument();
  });
});
