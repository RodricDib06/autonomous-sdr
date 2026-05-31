import { describe, it, expect, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../utils';
import { Sidebar } from '../../components/layout/Sidebar';
import { useAuthStore } from '../../store/authStore';

const mockUser = {
  id: 'user-1',
  email: 'test@example.com',
  role: 'rep' as const,
  is_active: true,
  created_at: '2024-01-01T00:00:00Z',
  last_login_at: null,
};

describe('Sidebar', () => {
  beforeEach(() => {
    useAuthStore.setState({ user: mockUser, accessToken: 'tok', refreshToken: 'ref' });
  });

  it('renders the AutonomousSDR logo text', () => {
    renderWithProviders(<Sidebar />);
    expect(screen.getByText('AutonomousSDR')).toBeInTheDocument();
  });

  it('renders main navigation links', () => {
    renderWithProviders(<Sidebar />);
    expect(screen.getByText('Dashboard')).toBeInTheDocument();
    expect(screen.getByText('Leads')).toBeInTheDocument();
    expect(screen.getByText('Pipeline')).toBeInTheDocument();
    expect(screen.getByText('A/B Tests')).toBeInTheDocument();
    expect(screen.getByText('Import')).toBeInTheDocument();
    expect(screen.getByText('Analytics')).toBeInTheDocument();
  });

  it('shows admin links for admin users', () => {
    useAuthStore.setState({ user: { ...mockUser, role: 'admin' }, accessToken: 'tok', refreshToken: 'ref' });
    renderWithProviders(<Sidebar />);
    expect(screen.getByText('Users')).toBeInTheDocument();
    expect(screen.getByText('Settings')).toBeInTheDocument();
  });

  it('shows user email in footer', () => {
    renderWithProviders(<Sidebar />);
    expect(screen.getByText('test@example.com')).toBeInTheDocument();
  });

  it('shows role badge', () => {
    renderWithProviders(<Sidebar />);
    expect(screen.getByText('rep')).toBeInTheDocument();
  });

  it('shows logout button', () => {
    renderWithProviders(<Sidebar />);
    expect(screen.getByTitle(/sign out/i)).toBeInTheDocument();
  });

  it('shows worker status after health check loads', async () => {
    renderWithProviders(<Sidebar />);
    // Health mock: worker_active: true
    await waitFor(() => {
      expect(screen.getByText(/worker/i)).toBeInTheDocument();
    });
  });
});
