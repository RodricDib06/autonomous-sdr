import { describe, it, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../utils';
import Dashboard from '../../pages/Dashboard';

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
});
