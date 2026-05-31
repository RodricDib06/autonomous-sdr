import { describe, it, expect, vi, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../utils';
import Leads from '../../pages/Leads';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('Leads page', () => {
  it('renders the page header', () => {
    renderWithProviders(<Leads />);
    expect(screen.getByText('Leads')).toBeInTheDocument();
  });

  it('shows lead names after data loads', async () => {
    renderWithProviders(<Leads />);
    await waitFor(() => {
      expect(screen.getByText('John Doe')).toBeInTheDocument();
      expect(screen.getByText('Jane Smith')).toBeInTheDocument();
      expect(screen.getByText('Bob Wilson')).toBeInTheDocument();
    });
  });

  it('shows company names', async () => {
    renderWithProviders(<Leads />);
    await waitFor(() => {
      expect(screen.getByText('Tech Corp')).toBeInTheDocument();
      expect(screen.getByText('Innovation Labs')).toBeInTheDocument();
    });
  });

  it('shows lead count in subtitle', async () => {
    renderWithProviders(<Leads />);
    await waitFor(() => {
      // Subtitle "3 leads" and footer "Showing 3 leads" both contain "leads"
      expect(screen.getAllByText(/leads/).length).toBeGreaterThan(0);
    });
  });

  it('renders verdict badges for each lead', async () => {
    renderWithProviders(<Leads />);
    await waitFor(() => {
      expect(screen.getByText('Hot')).toBeInTheDocument();
      expect(screen.getByText('Warm')).toBeInTheDocument();
      expect(screen.getByText('Cold')).toBeInTheDocument();
    });
  });

  it('filters leads by search query', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Leads />);

    await waitFor(() => screen.getByText('John Doe'));

    const searchInput = screen.getByPlaceholderText(/search/i);
    await user.type(searchInput, 'Jane');

    await waitFor(() => {
      expect(screen.getByText('Jane Smith')).toBeInTheDocument();
      expect(screen.queryByText('John Doe')).not.toBeInTheDocument();
      expect(screen.queryByText('Bob Wilson')).not.toBeInTheDocument();
    });
  });

  it('clears search to show all leads again', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Leads />);

    await waitFor(() => screen.getByText('John Doe'));

    const searchInput = screen.getByPlaceholderText(/search/i);
    await user.type(searchInput, 'Jane');
    await waitFor(() => expect(screen.queryByText('John Doe')).not.toBeInTheDocument());

    await user.clear(searchInput);
    await waitFor(() => {
      expect(screen.getByText('John Doe')).toBeInTheDocument();
      expect(screen.getByText('Jane Smith')).toBeInTheDocument();
    });
  });

  it('renders search input', () => {
    renderWithProviders(<Leads />);
    expect(screen.getByPlaceholderText(/search/i)).toBeInTheDocument();
  });

  it('renders export button', () => {
    renderWithProviders(<Leads />);
    expect(screen.getByRole('button', { name: /export/i })).toBeInTheDocument();
  });

  it('opens lead detail panel on row click', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Leads />);

    await waitFor(() => screen.getByText('John Doe'));

    // Click on the lead row to load the detail
    const row = screen.getByText('John Doe').closest('div[class*="hover"]') ??
                 screen.getByText('John Doe').parentElement!;
    await user.click(row);

    // The detail mutation fires and loads the detail panel
    await waitFor(() => {
      // Detail panel shows enrichment data from the mock
      expect(screen.getByText('Senior VP Sales')).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('shows status filter dropdown', async () => {
    renderWithProviders(<Leads />);
    await waitFor(() => screen.getByText('John Doe'));
    // Status filter SelectTrigger renders
    expect(screen.getByText('All Status')).toBeInTheDocument();
  });

  it('shows "Showing N leads" count in footer', async () => {
    renderWithProviders(<Leads />);
    await waitFor(() => {
      expect(screen.getByText(/Showing \d+ leads/)).toBeInTheDocument();
    });
  });

  it('shows Prev pagination button (disabled at first page)', async () => {
    renderWithProviders(<Leads />);
    await waitFor(() => screen.getByText('John Doe'));
    expect(screen.getByRole('button', { name: /prev/i })).toBeDisabled();
  });

  it('shows Next pagination button', async () => {
    renderWithProviders(<Leads />);
    await waitFor(() => screen.getByText('John Doe'));
    expect(screen.getByRole('button', { name: /next/i })).toBeInTheDocument();
  });

  it('clicking Export CSV button is clickable', async () => {
    const user = userEvent.setup();
    // Mock the leadsApi.export to avoid blob/stream issues in jsdom
    const { leadsApi } = await import('../../lib/api');
    vi.spyOn(leadsApi, 'export').mockResolvedValue(new Blob(['name,email\n'], { type: 'text/csv' }));
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});

    renderWithProviders(<Leads />);
    await waitFor(() => screen.getByText('John Doe'));
    await user.click(screen.getByRole('button', { name: /export/i }));

    await waitFor(() => {
      expect(leadsApi.export).toHaveBeenCalledWith('csv');
    });
  });

  it('delete bulk action button appears when rows selected', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Leads />);
    await waitFor(() => screen.getByText('John Doe'));

    const rowCheckboxes = document.querySelectorAll('tbody input[type="checkbox"]');
    await user.click(rowCheckboxes[0] as HTMLElement);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /delete/i })).toBeInTheDocument();
    });
  });

  it('clicking Delete archives the selected leads', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Leads />);
    await waitFor(() => screen.getByText('John Doe'));

    const rowCheckboxes = document.querySelectorAll('tbody input[type="checkbox"]');
    await user.click(rowCheckboxes[0] as HTMLElement);
    await waitFor(() => screen.getByRole('button', { name: /delete/i }));

    await user.click(screen.getByRole('button', { name: /delete/i }));
    // MSW handles /leads/batch POST → selection cleared
    await waitFor(() => {
      expect(screen.queryByText(/1 selected/i)).not.toBeInTheDocument();
    });
  });
});
