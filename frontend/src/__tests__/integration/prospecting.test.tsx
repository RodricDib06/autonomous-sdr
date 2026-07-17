import { describe, it, expect, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../utils';
import { ProspectingPanel } from '../../components/ProspectingPanel';
import { useAuthStore } from '../../store/authStore';
import { mockUser } from '../mocks/handlers';

beforeEach(() => {
  useAuthStore.setState({
    user: { ...mockUser, role: 'manager' },
    accessToken: 'tok',
    refreshToken: 'ref',
  });
});

describe('Prospecting panel', () => {
  it('shows the daily budget and recent run history with rejection breakdown', async () => {
    renderWithProviders(<ProspectingPanel />);
    await waitFor(() => {
      expect(screen.getByText('8/100 today')).toBeInTheDocument();
    });
    expect(screen.getByText(/industry: SaaS — synthetic/i)).toBeInTheDocument();
    expect(screen.getByText(/1 suppressed/i)).toBeInTheDocument();
    expect(screen.getByText(/2 duplicates/i)).toBeInTheDocument();
  });

  it('previews candidates through the quality gates', async () => {
    const user = userEvent.setup();
    renderWithProviders(<ProspectingPanel />);
    await waitFor(() => screen.getByText('Pipeline sourcing'));

    await user.type(screen.getByLabelText('Industry'), 'SaaS');
    await user.click(screen.getByRole('button', { name: /preview/i }));

    await waitFor(() => {
      expect(screen.getByText('Ava Keller')).toBeInTheDocument();
    });
    expect(screen.getByText('VP of Product')).toBeInTheDocument();
    expect(screen.getByText(/2 candidate\(s\) passed the gates/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /import 2 lead\(s\)/i })).toBeInTheDocument();
  });

  it('imports the previewed candidates', async () => {
    const user = userEvent.setup();
    renderWithProviders(<ProspectingPanel />);
    await waitFor(() => screen.getByText('Pipeline sourcing'));

    await user.click(screen.getByRole('button', { name: /preview/i }));
    await waitFor(() => screen.getByText('Ava Keller'));
    await user.click(screen.getByRole('button', { name: /import 2 lead\(s\)/i }));

    await waitFor(() => {
      expect(screen.getByText(/imported 2 lead\(s\)/i)).toBeInTheDocument();
    });
  });

  it('hides the import button from reps', async () => {
    useAuthStore.setState({ user: mockUser, accessToken: 'tok', refreshToken: 'ref' });
    const user = userEvent.setup();
    renderWithProviders(<ProspectingPanel />);
    await waitFor(() => screen.getByText('Pipeline sourcing'));

    await user.click(screen.getByRole('button', { name: /preview/i }));
    await waitFor(() => screen.getByText('Ava Keller'));
    expect(screen.queryByRole('button', { name: /import/i })).not.toBeInTheDocument();
  });
});
