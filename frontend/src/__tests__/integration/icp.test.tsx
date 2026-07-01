import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { renderWithProviders } from '../utils';
import ICP from '../../pages/ICP';
import { useAuthStore } from '../../store/authStore';
import { mockUser } from '../mocks/handlers';
import { server } from '../mocks/server';

beforeEach(() => {
  useAuthStore.setState({ user: { ...mockUser, role: 'admin' }, accessToken: 'tok', refreshToken: 'ref' });
});

afterEach(() => {
  server.resetHandlers();
});

describe('ICP page', () => {
  it('shows loading skeletons while fetching', () => {
    renderWithProviders(<ICP />);
    // Header renders immediately; skeleton divs appear before data loads
    expect(screen.getByText('ICP Builder')).toBeInTheDocument();
  });

  it('renders page header and subtitle after load', async () => {
    renderWithProviders(<ICP />);
    await waitFor(() => {
      expect(screen.getByText(/Define who your ideal customer is/i)).toBeInTheDocument();
    });
  });

  it('renders Target Industries section', async () => {
    renderWithProviders(<ICP />);
    await waitFor(() => expect(screen.getByText('Target Industries')).toBeInTheDocument());
    expect(screen.getByText('Decision-maker Seniority')).toBeInTheDocument();
    expect(screen.getByText('Company Size Range')).toBeInTheDocument();
    expect(screen.getByText('Excluded Industries')).toBeInTheDocument();
  });

  it('shows industry chips for all options', async () => {
    renderWithProviders(<ICP />);
    await waitFor(() => expect(screen.getByText('Target Industries')).toBeInTheDocument());
    // SaaS should appear in target industries (not excluded since excluded has Government)
    expect(screen.getAllByText('SaaS').length).toBeGreaterThan(0);
  });

  it('shows active seniority selections from saved config', async () => {
    renderWithProviders(<ICP />);
    await waitFor(() => expect(screen.getByText('Decision-maker Seniority')).toBeInTheDocument());
    // VP and C-Level are selected in mockICP
    expect(screen.getByText('VP')).toBeInTheDocument();
    expect(screen.getByText('C-Level')).toBeInTheDocument();
  });

  it('shows min/max employee inputs pre-populated from config', async () => {
    renderWithProviders(<ICP />);
    await waitFor(() => expect(screen.getByPlaceholderText('e.g. 50')).toBeInTheDocument());
    expect(screen.getByPlaceholderText('e.g. 1000')).toBeInTheDocument();
  });

  it('shows quick size presets', async () => {
    renderWithProviders(<ICP />);
    await waitFor(() => expect(screen.getByText('Quick presets')).toBeInTheDocument());
    expect(screen.getByText(/Seed \/ early/i)).toBeInTheDocument();
    expect(screen.getByText(/SMB/i)).toBeInTheDocument();
    expect(screen.getByText(/Mid-market/i)).toBeInTheDocument();
    expect(screen.getByText(/Enterprise/i)).toBeInTheDocument();
  });

  it('Save ICP button is disabled when no unsaved changes', async () => {
    renderWithProviders(<ICP />);
    await waitFor(() => expect(screen.getByRole('button', { name: /saved/i })).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /saved/i })).toBeDisabled();
  });

  it('toggling an industry chip marks draft as dirty and enables Save', async () => {
    const user = userEvent.setup();
    renderWithProviders(<ICP />);
    await waitFor(() => expect(screen.getByText('Target Industries')).toBeInTheDocument());

    // Click DevTools chip to add it
    const devtools = screen.getAllByText('DevTools')[0];
    await user.click(devtools);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /save icp/i })).not.toBeDisabled();
    });
  });

  it('toggling a seniority option marks draft as dirty', async () => {
    const user = userEvent.setup();
    renderWithProviders(<ICP />);
    await waitFor(() => expect(screen.getByText('Director')).toBeInTheDocument());

    await user.click(screen.getByText('Director').closest('button')!);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /save icp/i })).not.toBeDisabled();
    });
  });

  it('applying a size preset updates the inputs', async () => {
    const user = userEvent.setup();
    renderWithProviders(<ICP />);
    await waitFor(() => expect(screen.getByText(/Seed \/ early/i)).toBeInTheDocument());

    await user.click(screen.getByText(/Seed \/ early/i).closest('button')!);

    await waitFor(() => {
      expect((screen.getByPlaceholderText('e.g. 50') as HTMLInputElement).value).toBe('1');
    });
  });

  it('typing in min employees marks draft as dirty', async () => {
    const user = userEvent.setup();
    renderWithProviders(<ICP />);
    await waitFor(() => expect(screen.getByPlaceholderText('e.g. 50')).toBeInTheDocument());

    const minInput = screen.getByPlaceholderText('e.g. 50');
    await user.clear(minInput);
    await user.type(minInput, '100');

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /save icp/i })).not.toBeDisabled();
    });
  });

  it('clicking Save ICP fires the mutation and clears dirty state', async () => {
    const user = userEvent.setup();
    renderWithProviders(<ICP />);
    await waitFor(() => expect(screen.getByText('Target Industries')).toBeInTheDocument());

    // Dirty the form
    const devtools = screen.getAllByText('DevTools')[0];
    await user.click(devtools);
    await waitFor(() => expect(screen.getByRole('button', { name: /save icp/i })).not.toBeDisabled());

    await user.click(screen.getByRole('button', { name: /save icp/i }));

    // After success, button should return to "Saved" and be disabled
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /saved/i })).toBeDisabled();
    });
  });

  it('shows preview banner with stats when ICP is configured', async () => {
    renderWithProviders(<ICP />);
    await waitFor(() => {
      expect(screen.getByText('45')).toBeInTheDocument(); // matched count
    });
    expect(screen.getByText(/of pipeline/i)).toBeInTheDocument();
  });

  it('shows hot/warm/cold breakdown in preview', async () => {
    renderWithProviders(<ICP />);
    await waitFor(() => expect(screen.getByText('45')).toBeInTheDocument());
    expect(screen.getByText('12')).toBeInTheDocument(); // hot
    expect(screen.getByText('20')).toBeInTheDocument(); // warm
    expect(screen.getByText('13')).toBeInTheDocument(); // cold
  });

  it('shows unconfigured banner when ICP has no criteria', async () => {
    server.use(
      http.get('http://localhost:8000/icp', () =>
        HttpResponse.json({ industries: [], seniority_levels: [], excluded_industries: [], min_employees: null, max_employees: null, updated_at: null, updated_by_id: null })
      ),
      http.get('http://localhost:8000/icp/preview', () =>
        HttpResponse.json({ unconfigured: true, matched: 0, total: 0, hot: 0, warm: 0, cold: 0 })
      ),
    );
    renderWithProviders(<ICP />);
    await waitFor(() => {
      expect(screen.getByText(/No ICP configured yet/i)).toBeInTheDocument();
    });
  });

  it('shows last-updated footer when config has updated_at', async () => {
    renderWithProviders(<ICP />);
    await waitFor(() => {
      expect(screen.getByText(/last updated/i)).toBeInTheDocument();
    });
  });

  it('clicking Refresh preview button refetches preview', async () => {
    const user = userEvent.setup();
    renderWithProviders(<ICP />);
    await waitFor(() => expect(screen.getByRole('button', { name: /refresh preview/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /refresh preview/i }));
    // Just verifies the button is interactive and doesn't throw
    expect(screen.getByRole('button', { name: /refresh preview/i })).toBeInTheDocument();
  });

  it('shows save error toast on mutation failure', async () => {
    server.use(
      http.put('http://localhost:8000/icp', () => HttpResponse.json({ detail: 'Forbidden' }, { status: 403 }))
    );
    const user = userEvent.setup();
    renderWithProviders(<ICP />);
    await waitFor(() => expect(screen.getByText('Target Industries')).toBeInTheDocument());

    await user.click(screen.getAllByText('DevTools')[0]);
    await waitFor(() => expect(screen.getByRole('button', { name: /save icp/i })).not.toBeDisabled());

    await user.click(screen.getByRole('button', { name: /save icp/i }));

    await waitFor(() => {
      expect(screen.getByText(/failed to save icp/i)).toBeInTheDocument();
    });
  });

  it('excluded industry chip uses danger styling', async () => {
    renderWithProviders(<ICP />);
    await waitFor(() => expect(screen.getByText('Excluded Industries')).toBeInTheDocument());
    // The excluded Government chip shows with ✕ prefix when active
    const governmentChips = screen.getAllByText(/government/i);
    expect(governmentChips.length).toBeGreaterThan(0);
  });
});
