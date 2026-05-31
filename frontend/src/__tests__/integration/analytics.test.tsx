import { describe, it, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../utils';
import Analytics from '../../pages/Analytics';

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

  it('renders BANT Weights section', async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText('BANT Weight Evolution')).toBeInTheDocument();
    });
  });
});
