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
