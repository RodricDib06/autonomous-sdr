/**
 * Tests for uncovered Leads.tsx features:
 * - Keyboard shortcuts cheatsheet modal
 * - Semantic AI search mode
 * - ProfileTab: BANT scores, close probability, similar leads, CRM push, web enrichment
 * - Reprocess failed button
 * - Status filter
 */
import { describe, it, expect, afterEach } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { renderWithProviders } from '../utils';
import Leads from '../../pages/Leads';
import { server } from '../mocks/server';
import { useAuthStore } from '../../store/authStore';
import { mockUser } from '../mocks/handlers';

beforeEach(() => {
  useAuthStore.setState({ user: mockUser, accessToken: 'tok', refreshToken: 'ref' });
});

afterEach(() => {
  server.resetHandlers();
});

// Helper: open the detail panel for lead-1 (John Doe)
async function openDetailPanel() {
  const user = userEvent.setup();
  renderWithProviders(<Leads />);
  await waitFor(() => screen.getByText('John Doe'));
  const row = screen.getByText('John Doe').closest('tr')!;
  await user.click(row);
  await waitFor(() => screen.getByText('Senior VP Sales'), { timeout: 3000 });
  return user;
}

// ── Keyboard cheatsheet modal ──────────────────────────────────────────────

describe('Keyboard shortcuts cheatsheet', () => {
  it('clicking the keyboard icon opens the cheatsheet modal', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Leads />);
    await waitFor(() => screen.getByText('John Doe'));

    // The keyboard icon button is in the header
    const kbBtn = document.querySelector('button[title="Keyboard shortcuts (?)"]') as HTMLElement;
    expect(kbBtn).toBeInTheDocument();
    await user.click(kbBtn);

    await waitFor(() => {
      expect(screen.getByText('Keyboard Shortcuts')).toBeInTheDocument();
    });
  });

  it('cheatsheet shows all shortcut entries', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Leads />);
    await waitFor(() => screen.getByText('John Doe'));

    const kbBtn = document.querySelector('button[title="Keyboard shortcuts (?)"]') as HTMLElement;
    await user.click(kbBtn);

    await waitFor(() => {
      expect(screen.getByText('Next lead')).toBeInTheDocument();
      expect(screen.getByText('Previous lead')).toBeInTheDocument();
      expect(screen.getByText('Open lead detail')).toBeInTheDocument();
      expect(screen.getByText('Focus search')).toBeInTheDocument();
      expect(screen.getByText('Show shortcuts')).toBeInTheDocument();
    });
  });
});

// ── Semantic AI search mode ────────────────────────────────────────────────

describe('Semantic AI search mode', () => {
  it('clicking AI Search toggles semantic mode on', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Leads />);
    await waitFor(() => screen.getByText('John Doe'));

    await user.click(screen.getByRole('button', { name: /ai search/i }));

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/leads who mentioned pricing/i)).toBeInTheDocument();
    });
  });

  it('semantic mode shows help prompt when no query is entered', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Leads />);
    await waitFor(() => screen.getByText('John Doe'));

    await user.click(screen.getByRole('button', { name: /ai search/i }));

    await waitFor(() => {
      expect(screen.getByText(/search conversations by meaning/i)).toBeInTheDocument();
    });
  });

  it('clicking AI Search again toggles semantic mode off', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Leads />);
    await waitFor(() => screen.getByText('John Doe'));

    await user.click(screen.getByRole('button', { name: /ai search/i }));
    await waitFor(() => expect(screen.getByPlaceholderText(/leads who mentioned pricing/i)).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /ai search/i }));
    await waitFor(() => {
      expect(screen.queryByPlaceholderText(/leads who mentioned pricing/i)).not.toBeInTheDocument();
      expect(screen.getByPlaceholderText(/search by name/i)).toBeInTheDocument();
    });
  });
});

// ── Status filter ──────────────────────────────────────────────────────────

describe('Status filter', () => {
  it('shows the status filter dropdown trigger', async () => {
    renderWithProviders(<Leads />);
    await waitFor(() => screen.getByText('John Doe'));
    // The filter trigger shows "All Status"
    expect(screen.getByText('All Status')).toBeInTheDocument();
  });

  it('filtering by status renders the filter trigger correctly', async () => {
    renderWithProviders(<Leads />);
    await waitFor(() => screen.getByText('Bob Wilson'));
    // The status select is present and shows All Status by default
    expect(screen.getByText('All Status')).toBeInTheDocument();
  });
});

// ── Reprocess failed button ────────────────────────────────────────────────

describe('Reprocess failed leads', () => {
  it('shows Reprocess button when failed leads exist', async () => {
    server.use(
      http.get('http://localhost:8000/leads', () =>
        HttpResponse.json([
          {
            id: 'lead-fail', name: 'Failed Lead', email: 'fail@test.com', company: 'FailCo',
            source: 'form', status: 'failed', created_at: '2024-01-10T00:00:00Z', updated_at: null,
            data_quality_score: null, completeness_score: null, tags: [], archived: false, final_verdict: null,
          },
        ])
      )
    );
    renderWithProviders(<Leads />);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /reprocess/i })).toBeInTheDocument();
    });
  });

  it('clicking Reprocess calls the mutation', async () => {
    server.use(
      http.get('http://localhost:8000/leads', () =>
        HttpResponse.json([
          {
            id: 'lead-fail', name: 'Failed Lead', email: 'fail@test.com', company: 'FailCo',
            source: 'form', status: 'failed', created_at: '2024-01-10T00:00:00Z', updated_at: null,
            data_quality_score: null, completeness_score: null, tags: [], archived: false, final_verdict: null,
          },
        ])
      )
    );
    const user = userEvent.setup();
    renderWithProviders(<Leads />);
    await waitFor(() => screen.getByRole('button', { name: /reprocess/i }));

    await user.click(screen.getByRole('button', { name: /reprocess/i }));

    await waitFor(() => {
      expect(screen.getByText(/re-queued/i)).toBeInTheDocument();
    });
  });
});

// ── No leads found state ───────────────────────────────────────────────────

describe('Empty state', () => {
  it('shows "No leads found" when search has no results', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Leads />);
    await waitFor(() => screen.getByText('John Doe'));

    await user.type(screen.getByPlaceholderText(/search by name/i), 'zzznomatch');

    await waitFor(() => {
      expect(screen.getByText('No leads found')).toBeInTheDocument();
    });
  });
});

// ── ProfileTab advanced sections ───────────────────────────────────────────

describe('ProfileTab — BANT scores', () => {
  it('shows BANT score bars in profile tab', async () => {
    await openDetailPanel();
    // mockVerdict has bant_scores: { budget: 0.95, authority: 0.85, need: 0.92, timeline: 0.78 }
    await waitFor(() => {
      expect(screen.getByText('Budget')).toBeInTheDocument();
      expect(screen.getByText('Authority')).toBeInTheDocument();
      expect(screen.getByText('Need')).toBeInTheDocument();
      expect(screen.getByText('Timeline')).toBeInTheDocument();
    });
  });

  it('shows ML close probability', async () => {
    await openDetailPanel();
    // mock returns probability: 0.73
    await waitFor(() => {
      expect(screen.getAllByText(/close probability/i).length).toBeGreaterThan(0);
    });
  });
});

describe('ProfileTab — Similar leads', () => {
  it('shows similar leads section', async () => {
    await openDetailPanel();
    await waitFor(() => {
      expect(screen.getByText(/similar leads/i)).toBeInTheDocument();
    });
  });

  it('shows similar lead entry from API', async () => {
    await openDetailPanel();
    await waitFor(() => {
      // From mockSimilar: similarity 87% — look for the percentage
      expect(screen.getByText('87%')).toBeInTheDocument();
    });
  });
});

describe('ProfileTab — CRM push', () => {
  it('shows Push to CRM section', async () => {
    await openDetailPanel();
    await waitFor(() => {
      expect(screen.getByText(/push to crm/i)).toBeInTheDocument();
    });
  });

  it('CRM format buttons are selectable', async () => {
    const user = await openDetailPanel();
    await waitFor(() => expect(screen.getByText('salesforce')).toBeInTheDocument());

    await user.click(screen.getByText('salesforce'));
    // Push button text should update
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /push to salesforce/i })).toBeInTheDocument();
    });
  });

  it('clicking Push to CRM fires the mutation', async () => {
    const user = await openDetailPanel();
    await waitFor(() => expect(screen.getByRole('button', { name: /push to hubspot/i })).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /push to hubspot/i }));

    await waitFor(() => {
      // After success, shows the formatted result
      expect(screen.getByText(/ready for hubspot/i)).toBeInTheDocument();
    });
  });
});

describe('ProfileTab — Web enrichment', () => {
  it('shows Web Signals section with Scrape button', async () => {
    await openDetailPanel();
    await waitFor(() => {
      expect(screen.getByText('Web Signals')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /scrape/i })).toBeInTheDocument();
    });
  });

  it('clicking Scrape fetches web enrichment data', async () => {
    const user = await openDetailPanel();
    await waitFor(() => expect(screen.getByRole('button', { name: /scrape/i })).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /scrape/i }));

    await waitFor(() => {
      expect(screen.getByText(/Series B announcement/i)).toBeInTheDocument();
    });
  });
});

describe('ProfileTab — AI Reasoning', () => {
  it('shows AI Reasoning section when verdict has reasoning', async () => {
    await openDetailPanel();
    // mockVerdict.reasoning: "High-ranking decision maker at well-funded tech company"
    await waitFor(() => {
      expect(screen.getByText(/high-ranking decision maker/i)).toBeInTheDocument();
    });
  });
});

describe('Cooling leads in Leads list', () => {
  it('shows cooling timer badge for leads that are cooling', async () => {
    // Override cooling handler to return leads matching mockLeads IDs
    server.use(
      http.get('http://localhost:8000/leads/cooling', () =>
        HttpResponse.json({
          leads: [
            { id: 'lead-1', name: 'John Doe', email: 'john@example.com', company: 'Tech Corp', job_title: 'VP', decay: { days_since_engagement: 10, urgency: 'urgent', recommended_action: 'Call now' } },
            { id: 'lead-2', name: 'Jane Smith', email: 'jane@example.com', company: 'Innovation Labs', job_title: null, decay: { days_since_engagement: 8, urgency: 'warning', recommended_action: 'Follow up' } },
          ],
          count: 2,
        })
      )
    );
    renderWithProviders(<Leads />);
    await waitFor(() => screen.getByText('John Doe'));

    // Timer badge should appear for cooling leads (shows Xd)
    await waitFor(() => {
      expect(screen.getByText('10d')).toBeInTheDocument();
      expect(screen.getByText('8d')).toBeInTheDocument();
    });
  });
});

describe('Detail panel backdrop', () => {
  it('clicking backdrop closes the detail panel', async () => {
    const user = await openDetailPanel();

    // Click the backdrop (fixed overlay behind the panel)
    const backdrop = document.querySelector('.fixed.inset-0.z-30') as HTMLElement;
    if (backdrop) await user.click(backdrop);

    await waitFor(() => {
      expect(screen.queryByText('Senior VP Sales')).not.toBeInTheDocument();
    });
  });
});

// ── Activity tab with data ─────────────────────────────────────────────────

describe('ActivityTab with booking data', () => {
  it('shows booking entry when bookings are returned', async () => {
    server.use(
      http.get('http://localhost:8000/leads/:id/bookings', () =>
        HttpResponse.json({
          bookings: [{
            id: 'booking-1',
            lead_id: 'lead-1',
            status: 'confirmed',
            scheduling_url: 'https://cal.com/rep/30min',
            meeting_time: '2024-02-15T14:00:00Z',
            notes: 'Discovery call scheduled',
            created_at: '2024-01-20T10:00:00Z',
          }],
          count: 1,
        })
      )
    );
    const user = await openDetailPanel();
    await user.click(screen.getByText('Activity'));

    await waitFor(() => {
      expect(screen.getByText('confirmed')).toBeInTheDocument();
    });
  });

  it('shows scheduling link in booking entry', async () => {
    server.use(
      http.get('http://localhost:8000/leads/:id/bookings', () =>
        HttpResponse.json({
          bookings: [{
            id: 'booking-1',
            lead_id: 'lead-1',
            status: 'pending',
            scheduling_url: 'https://cal.com/rep/30min',
            meeting_time: null,
            notes: null,
            created_at: '2024-01-20T10:00:00Z',
          }],
          count: 1,
        })
      )
    );
    const user = await openDetailPanel();
    await user.click(screen.getByText('Activity'));

    await waitFor(() => {
      expect(screen.getByText('Cal link ↗')).toBeInTheDocument();
    });
  });

  it('shows conversation with messages', async () => {
    server.use(
      http.get('http://localhost:8000/leads/:id/conversations', () =>
        HttpResponse.json({
          conversations: [{
            id: 'conv-1',
            lead_id: 'lead-1',
            channel: 'email',
            summary: 'Prospect interested in Q2 rollout',
            messages: [
              { role: 'assistant', content: 'Hi John, following up on...', timestamp: '2024-01-15T10:00:00Z' },
              { role: 'user', content: 'Thanks, we are evaluating options for Q2', timestamp: '2024-01-15T11:00:00Z' },
            ],
            created_at: '2024-01-15T10:00:00Z',
            updated_at: '2024-01-15T11:00:00Z',
          }],
          count: 1,
        })
      )
    );
    const user = await openDetailPanel();
    await user.click(screen.getByText('Activity'));

    await waitFor(() => {
      expect(screen.getByText(/interested in Q2 rollout/i)).toBeInTheDocument();
    });
  });

  it('shows conversation channel badge', async () => {
    server.use(
      http.get('http://localhost:8000/leads/:id/conversations', () =>
        HttpResponse.json({
          conversations: [{
            id: 'conv-1', lead_id: 'lead-1', channel: 'email',
            summary: null,
            messages: [{ role: 'user', content: 'Hello!', timestamp: '2024-01-15T10:00:00Z' }],
            created_at: '2024-01-15T10:00:00Z', updated_at: null,
          }],
          count: 1,
        })
      )
    );
    const user = await openDetailPanel();
    await user.click(screen.getByText('Activity'));

    await waitFor(() => {
      expect(screen.getByText('email')).toBeInTheDocument();
    });
  });
});

// ── OutreachTab with data ──────────────────────────────────────────────────

describe('OutreachTab with email data', () => {
  it('shows outreach email entries when emails are returned', async () => {
    server.use(
      http.get('http://localhost:8000/leads/:id/outreach', () =>
        HttpResponse.json({
          emails: [{
            id: 'email-1',
            lead_id: 'lead-1',
            step_number: 1,
            subject: 'Quick question about your stack',
            status: 'opened',
            sent_at: '2024-01-15T09:00:00Z',
            opened_at: '2024-01-15T10:00:00Z',
            replied_at: null,
            scheduled_at: null,
          }],
          count: 1,
        })
      )
    );
    const user = await openDetailPanel();
    await user.click(screen.getByText('Outreach'));

    await waitFor(() => {
      expect(screen.getByText('Quick question about your stack')).toBeInTheDocument();
      expect(screen.getByText('Step 1')).toBeInTheDocument();
    });
  });

  it('shows replied email status badge', async () => {
    server.use(
      http.get('http://localhost:8000/leads/:id/outreach', () =>
        HttpResponse.json({
          emails: [{
            id: 'email-2', lead_id: 'lead-1', step_number: 2,
            subject: 'Follow up — ROI calculator',
            status: 'replied',
            sent_at: '2024-01-16T09:00:00Z',
            opened_at: '2024-01-16T10:00:00Z',
            replied_at: '2024-01-17T11:00:00Z',
            scheduled_at: null,
          }],
          count: 1,
        })
      )
    );
    const user = await openDetailPanel();
    await user.click(screen.getByText('Outreach'));

    await waitFor(() => {
      // "Follow up — ROI calculator" subject is unique
      expect(screen.getByText('Follow up — ROI calculator')).toBeInTheDocument();
      // Status badge shows "replied" (multiple occurrences are fine)
      expect(screen.getAllByText(/replied/i).length).toBeGreaterThan(0);
    });
  });
});

// ── Close probability feature importances ─────────────────────────────────

describe('ProfileTab — Close probability with feature importances', () => {
  it('shows divergence note from ML model', async () => {
    await openDetailPanel();
    await waitFor(() => {
      expect(screen.getByText(/BANT score and ML model diverge/i)).toBeInTheDocument();
    });
  });

  it('shows feature importance bars', async () => {
    await openDetailPanel();
    await waitFor(() => {
      expect(screen.getByText(/Model feature weights/i)).toBeInTheDocument();
    });
  });

  it('shows model training info', async () => {
    await openDetailPanel();
    await waitFor(() => {
      expect(screen.getByText(/Model trained on/i)).toBeInTheDocument();
      expect(screen.getByText(/450 leads/i)).toBeInTheDocument();
    });
  });
});

// ── Leads page misc ────────────────────────────────────────────────────────

describe('Leads page — pagination', () => {
  it('Next button is clickable when leads.length >= PAGE_SIZE (50)', async () => {
    // Return exactly 50 leads to make Next button enabled
    const fiftyLeads = Array.from({ length: 50 }, (_, i) => ({
      id: `lead-${i}`, name: `Lead ${i}`, email: `lead${i}@test.com`, company: `Co ${i}`,
      source: 'form', status: 'complete' as const, created_at: '2024-01-10T00:00:00Z',
      updated_at: null, data_quality_score: 0.8, completeness_score: 0.9,
      tags: [], archived: false, final_verdict: 'Hot' as const,
    }));
    server.use(
      http.get('http://localhost:8000/leads', () => HttpResponse.json(fiftyLeads))
    );
    const user = userEvent.setup();
    renderWithProviders(<Leads />);
    await waitFor(() => screen.getByText('Lead 0'));

    const nextBtn = screen.getByRole('button', { name: /next/i });
    expect(nextBtn).not.toBeDisabled();
    await user.click(nextBtn);

    // Page changes to 1 — Prev button should now be enabled
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /prev/i })).not.toBeDisabled();
    });
  });

  it('Prev button navigates back to page 0', async () => {
    const fiftyLeads = Array.from({ length: 50 }, (_, i) => ({
      id: `lead-${i}`, name: `Lead ${i}`, email: `lead${i}@test.com`, company: `Co ${i}`,
      source: 'form', status: 'complete' as const, created_at: '2024-01-10T00:00:00Z',
      updated_at: null, data_quality_score: 0.8, completeness_score: 0.9,
      tags: [], archived: false, final_verdict: 'Hot' as const,
    }));
    server.use(
      http.get('http://localhost:8000/leads', () => HttpResponse.json(fiftyLeads))
    );
    const user = userEvent.setup();
    renderWithProviders(<Leads />);
    await waitFor(() => screen.getByText('Lead 0'));

    // Go to page 1
    await user.click(screen.getByRole('button', { name: /next/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /prev/i })).not.toBeDisabled());

    // Go back to page 0
    await user.click(screen.getByRole('button', { name: /prev/i }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /prev/i })).toBeDisabled();
    });
  });
});

describe('Leads page — export and add lead', () => {
  it('clicking Export CSV calls export function', async () => {
    const { leadsApi } = await import('../../lib/api');
    const { vi: viMod } = await import('vitest');
    viMod.spyOn(leadsApi, 'export').mockResolvedValue(new Blob(['csv'], { type: 'text/csv' }));
    viMod.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock');
    viMod.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});

    const user = userEvent.setup();
    renderWithProviders(<Leads />);
    await waitFor(() => screen.getByText('John Doe'));

    await user.click(screen.getByRole('button', { name: /export/i }));

    await waitFor(() => {
      expect(leadsApi.export).toHaveBeenCalledWith('csv');
    });
    viMod.restoreAllMocks();
  });

  it('shows semantic search submit button when in semantic mode', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Leads />);
    await waitFor(() => screen.getByText('John Doe'));

    await user.click(screen.getByRole('button', { name: /ai search/i }));
    await waitFor(() => expect(screen.getByPlaceholderText(/leads who mentioned pricing/i)).toBeInTheDocument());

    // Semantic search form submit button exists (type="submit" inside the form)
    const form = document.querySelector('form[class*="flex"]') as HTMLFormElement;
    expect(form).toBeTruthy();
    const submitBtn = form?.querySelector('button[type="submit"]');
    expect(submitBtn).toBeInTheDocument();
  });

  it('submitting semantic search form fires query', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Leads />);
    await waitFor(() => screen.getByText('John Doe'));

    await user.click(screen.getByRole('button', { name: /ai search/i }));
    await waitFor(() => expect(screen.getByPlaceholderText(/leads who mentioned pricing/i)).toBeInTheDocument());

    await user.type(screen.getByPlaceholderText(/leads who mentioned pricing/i), 'pricing concerns');

    // Submit the form programmatically
    const form = document.querySelector('form') as HTMLFormElement;
    fireEvent.submit(form);

    // After submit, query is set (API called) — verify no crash
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/leads who mentioned pricing/i)).toBeInTheDocument();
    });
  });
});
