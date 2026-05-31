import { describe, it, expect, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../utils';
import { Layout } from '../../../components/layout/Layout';
import { useAuthStore } from '../../../store/authStore';
import { mockUser } from '../../mocks/handlers';

describe('Layout', () => {
  beforeEach(() => {
    useAuthStore.setState({ user: mockUser, accessToken: 'tok', refreshToken: 'ref' });
  });

  it('renders the main content area', () => {
    const { container } = renderWithProviders(<Layout />);
    expect(container.querySelector('main')).toBeInTheDocument();
  });

  it('renders the sidebar', () => {
    renderWithProviders(<Layout />);
    expect(screen.getByText('AutonomousSDR')).toBeInTheDocument();
  });
});
