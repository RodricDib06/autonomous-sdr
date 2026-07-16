import { describe, it, expect, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { renderWithProviders } from '../utils';
import Backtests from '../../pages/Backtests';
import { useAuthStore } from '../../store/authStore';
import { mockUser } from '../mocks/handlers';
import { server } from '../mocks/server';

beforeEach(() => {
  useAuthStore.setState({
    user: { ...mockUser, role: 'manager' },
    accessToken: 'tok',
    refreshToken: 'ref',
  });
});

describe('Backtests page', () => {
  it('renders the upload zone with expected CSV columns', async () => {
    renderWithProviders(<Backtests />);
    expect(screen.getByText(/drop last quarter's crm export/i)).toBeInTheDocument();
    for (const col of ['name', 'email', 'company', 'outcome']) {
      expect(screen.getByText(col)).toBeInTheDocument();
    }
  });

  it('lists previous runs and shows the calibration report for the latest', async () => {
    renderWithProviders(<Backtests />);

    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /q1_deals\.csv/i })).toBeInTheDocument();
    });

    // Headline stats from the summary
    await waitFor(() => {
      expect(screen.getByText('Hot recall')).toBeInTheDocument();
    });
    expect(screen.getByText('80%')).toBeInTheDocument();          // hot_recall
    expect(screen.getByText('2.67×')).toBeInTheDocument();        // hot_lift
    expect(screen.getByText(/of your closed-won deals were flagged hot/i)).toBeInTheDocument();

    // Verdict × outcome matrix
    expect(screen.getByText('Verdict vs. reality')).toBeInTheDocument();

    // Skipped-row report
    expect(screen.getByText(/1 row\(s\) skipped/i)).toBeInTheDocument();
    expect(screen.getByText(/unrecognised outcome "maybe"/i)).toBeInTheDocument();
  });

  it('shows scored records and filters to misses only', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Backtests />);

    await waitFor(() => {
      expect(screen.getByText('Jane Doe')).toBeInTheDocument();
    });
    expect(screen.getByText('Bob Roe')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /misses only/i }));

    // Bob is Hot-but-lost (a miss); Jane is Hot-and-won (not a miss)
    await waitFor(() => {
      expect(screen.queryByText('Jane Doe')).not.toBeInTheDocument();
    });
    expect(screen.getByText('Bob Roe')).toBeInTheDocument();
    expect(screen.getByText(/where the agent and reality disagreed/i)).toBeInTheDocument();
  });

  it('uploads a CSV and selects the new run', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Backtests />);
    await waitFor(() => screen.getByRole('tab', { name: /q1_deals\.csv/i }));

    const file = new File(['name,email,company,outcome\nJane,j@a.io,Acme,won'], 'upload.csv', { type: 'text/csv' });
    await user.upload(screen.getByLabelText('Backtest CSV file'), file);

    await waitFor(() => {
      expect(screen.getByText(/scored 40 leads from upload\.csv/i)).toBeInTheDocument();
    });
  });

  it('surfaces a helpful error when the CSV is rejected', async () => {
    server.use(
      http.post('http://localhost:8000/backtests', () =>
        HttpResponse.json({ detail: 'Missing required columns: outcome' }, { status: 422 })
      )
    );
    const user = userEvent.setup();
    renderWithProviders(<Backtests />);

    const file = new File(['name,email\n'], 'bad.csv', { type: 'text/csv' });
    await user.upload(screen.getByLabelText('Backtest CSV file'), file);

    await waitFor(() => {
      expect(screen.getByText(/missing required columns: outcome/i)).toBeInTheDocument();
    });
  });

  it('shows the empty state when no runs exist', async () => {
    server.use(
      http.get('http://localhost:8000/backtests', () =>
        HttpResponse.json({ total: 0, runs: [] })
      )
    );
    renderWithProviders(<Backtests />);
    await waitFor(() => {
      expect(screen.getByText('No backtests yet')).toBeInTheDocument();
    });
  });

  it('marks records with defaulted dimensions in the notes column', async () => {
    renderWithProviders(<Backtests />);
    await waitFor(() => screen.getByText('Bob Roe'));
    const bobRow = screen.getByText('Bob Roe').closest('tr')!;
    expect(within(bobRow).getByText(/defaulted: need/i)).toBeInTheDocument();
  });
});
