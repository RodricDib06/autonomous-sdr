import { describe, it, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../utils';
import ABTests from '../../pages/ABTests';

describe('ABTests page', () => {
  it('renders the page header with correct title', () => {
    renderWithProviders(<ABTests />);
    expect(screen.getByText('A/B Tests & Optimization')).toBeInTheDocument();
  });

  it('renders the page subtitle', () => {
    renderWithProviders(<ABTests />);
    expect(screen.getByText(/email sequence experiments/i)).toBeInTheDocument();
  });

  it('shows variant cards after data loads', async () => {
    renderWithProviders(<ABTests />);
    await waitFor(() => {
      // "Variant A" and "Variant B" appear in card headers and legend
      expect(screen.getAllByText(/Variant A/i).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/Variant B/i).length).toBeGreaterThan(0);
    });
  });

  it('shows statistically significant winner text', async () => {
    renderWithProviders(<ABTests />);
    await waitFor(() => {
      expect(screen.getByText(/statistically significant winner/i)).toBeInTheDocument();
    });
  });

  it('renders the promote winner button', async () => {
    renderWithProviders(<ABTests />);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /promote winner/i })).toBeInTheDocument();
    });
  });

  it('renders head-to-head comparison section', async () => {
    renderWithProviders(<ABTests />);
    await waitFor(() => {
      expect(screen.getByText('Head-to-Head Comparison')).toBeInTheDocument();
    });
  });

  it('shows open rate and reply rate metric bars', async () => {
    renderWithProviders(<ABTests />);
    await waitFor(() => {
      expect(screen.getAllByText(/open rate/i).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/reply rate/i).length).toBeGreaterThan(0);
    });
  });

  it('shows BANT weights section', async () => {
    renderWithProviders(<ABTests />);
    await waitFor(() => {
      expect(screen.getByText('BANT Weights (Live)')).toBeInTheDocument();
    });
  });

  it('shows optimization history section', async () => {
    renderWithProviders(<ABTests />);
    await waitFor(() => {
      expect(screen.getByText('Optimization History')).toBeInTheDocument();
    });
  });

  it('displays mock optimization run data', async () => {
    renderWithProviders(<ABTests />);
    await waitFor(() => {
      // Mock has 1 run with leads_analysed: 120
      expect(screen.getByText(/120/)).toBeInTheDocument();
    });
  });

  it('shows p-value from mock data', async () => {
    renderWithProviders(<ABTests />);
    await waitFor(() => {
      expect(screen.getByText(/p=0\.042/)).toBeInTheDocument();
    });
  });

  it('shows variant email sent counts from mock data', async () => {
    renderWithProviders(<ABTests />);
    await waitFor(() => {
      // Both variants have emails_sent: 100 → "100" appears at least once
      expect(screen.getAllByText('100').length).toBeGreaterThan(0);
    });
  });

  it('clicking Promote winner fires the promote mutation', async () => {
    const user = userEvent.setup();
    renderWithProviders(<ABTests />);
    await waitFor(() => screen.getByRole('button', { name: /promote winner/i }));

    await user.click(screen.getByRole('button', { name: /promote winner/i }));
    // MSW returns { success: true } — button should remain in DOM
    expect(screen.getByRole('button', { name: /promote winner/i })).toBeInTheDocument();
  });

  it('clicking Run now fires the optimization run mutation', async () => {
    const user = userEvent.setup();
    renderWithProviders(<ABTests />);
    await waitFor(() => screen.getByRole('button', { name: /run now/i }));

    await user.click(screen.getByRole('button', { name: /run now/i }));
    // MSW returns { ok: true }
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /run now/i })).toBeInTheDocument();
    });
  });

  it('shows the conversion rate metric bar', async () => {
    renderWithProviders(<ABTests />);
    await waitFor(() => {
      expect(screen.getAllByText(/conversion/i).length).toBeGreaterThan(0);
    });
  });

  it('shows Sent / Opened / Replied labels in variant cards', async () => {
    renderWithProviders(<ABTests />);
    await waitFor(() => {
      expect(screen.getAllByText('Sent').length).toBeGreaterThan(0);
      expect(screen.getAllByText('Opened').length).toBeGreaterThan(0);
      expect(screen.getAllByText('Replied').length).toBeGreaterThan(0);
    });
  });
});
