import { describe, it, expect, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../utils';
import { ProtectedRoute } from '../../../components/ProtectedRoute';
import { useAuthStore } from '../../../store/authStore';
import { mockUser } from '../../mocks/handlers';

beforeEach(() => {
  useAuthStore.setState({ user: null, accessToken: null, refreshToken: null });
});

describe('ProtectedRoute', () => {
  it('renders children when user is authenticated', () => {
    useAuthStore.setState({ user: mockUser, accessToken: 'tok', refreshToken: 'ref' });
    renderWithProviders(
      <ProtectedRoute>
        <div>Protected Content</div>
      </ProtectedRoute>
    );
    expect(screen.getByText('Protected Content')).toBeInTheDocument();
  });

  it('does not render children when no user (redirects)', () => {
    renderWithProviders(
      <ProtectedRoute>
        <div>Protected Content</div>
      </ProtectedRoute>
    );
    expect(screen.queryByText('Protected Content')).not.toBeInTheDocument();
  });

  it('does not render when requireAdmin and user is rep', () => {
    useAuthStore.setState({ user: { ...mockUser, role: 'rep' }, accessToken: 'tok', refreshToken: 'ref' });
    renderWithProviders(
      <ProtectedRoute requireAdmin>
        <div>Admin Only</div>
      </ProtectedRoute>
    );
    expect(screen.queryByText('Admin Only')).not.toBeInTheDocument();
  });

  it('renders when requireAdmin and user is admin', () => {
    useAuthStore.setState({ user: { ...mockUser, role: 'admin' }, accessToken: 'tok', refreshToken: 'ref' });
    renderWithProviders(
      <ProtectedRoute requireAdmin>
        <div>Admin Only</div>
      </ProtectedRoute>
    );
    expect(screen.getByText('Admin Only')).toBeInTheDocument();
  });

  it('does not render when requireManager and user is rep', () => {
    useAuthStore.setState({ user: { ...mockUser, role: 'rep' }, accessToken: 'tok', refreshToken: 'ref' });
    renderWithProviders(
      <ProtectedRoute requireManager>
        <div>Manager Content</div>
      </ProtectedRoute>
    );
    expect(screen.queryByText('Manager Content')).not.toBeInTheDocument();
  });

  it('renders when requireManager and user is manager', () => {
    useAuthStore.setState({ user: { ...mockUser, role: 'manager' }, accessToken: 'tok', refreshToken: 'ref' });
    renderWithProviders(
      <ProtectedRoute requireManager>
        <div>Manager Content</div>
      </ProtectedRoute>
    );
    expect(screen.getByText('Manager Content')).toBeInTheDocument();
  });

  it('renders without crashing when no children (uses Outlet)', () => {
    useAuthStore.setState({ user: mockUser, accessToken: 'tok', refreshToken: 'ref' });
    const { container } = renderWithProviders(<ProtectedRoute />);
    expect(container).toBeTruthy();
  });
});
