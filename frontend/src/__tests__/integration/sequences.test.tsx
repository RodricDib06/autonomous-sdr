import { describe, it, expect, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../utils';
import Sequences from '../../pages/Sequences';
import { useAuthStore } from '../../store/authStore';
import { mockUser } from '../mocks/handlers';

beforeEach(() => {
  useAuthStore.setState({
    user: { ...mockUser, role: 'manager' },
    accessToken: 'tok',
    refreshToken: 'ref',
  });
});

describe('Sequences page', () => {
  it('lists sequences with shared badge and stats', async () => {
    renderWithProviders(<Sequences />);
    await waitFor(() => {
      expect(screen.getByText('Standard 3-Step (Variant A)')).toBeInTheDocument();
    });
    expect(screen.getByText('My Custom Cadence')).toBeInTheDocument();
    expect(screen.getByText('shared')).toBeInTheDocument();
    expect(screen.getByText('42 sent')).toBeInTheDocument();
  });

  it('opens the editor dialog with step fields', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Sequences />);
    await waitFor(() => screen.getByRole('button', { name: /new sequence/i }));

    await user.click(screen.getByRole('button', { name: /new sequence/i }));
    await waitFor(() => screen.getByRole('heading', { name: 'New sequence' }));

    expect(screen.getByPlaceholderText(/enterprise 3-step/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/quick question about \{company\}/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /add step/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /create sequence/i })).toBeDisabled();
  });

  it('enables create once name and step content are filled', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Sequences />);
    await waitFor(() => screen.getByRole('button', { name: /new sequence/i }));
    await user.click(screen.getByRole('button', { name: /new sequence/i }));
    await waitFor(() => screen.getByRole('heading', { name: 'New sequence' }));

    await user.type(screen.getByPlaceholderText(/enterprise 3-step/i), 'Test Cadence');
    await user.type(screen.getByPlaceholderText(/quick question about \{company\}/i), 'Subject line');
    await user.type(screen.getByPlaceholderText(/hi \{first_name\}/i), 'Body text');

    expect(screen.getByRole('button', { name: /create sequence/i })).toBeEnabled();
  });

  it('hides authoring controls for reps', async () => {
    useAuthStore.setState({ user: mockUser, accessToken: 'tok', refreshToken: 'ref' });
    renderWithProviders(<Sequences />);
    await waitFor(() => screen.getByText('My Custom Cadence'));
    expect(screen.queryByRole('button', { name: /new sequence/i })).not.toBeInTheDocument();
  });
});
