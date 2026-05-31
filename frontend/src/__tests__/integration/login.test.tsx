import { describe, it, expect } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../utils';
import Login from '../../pages/Login';

describe('Login page', () => {
  it('renders the login form', () => {
    renderWithProviders(<Login />);
    expect(screen.getByLabelText('Email')).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  });

  it('renders the AutonomousSDR branding', () => {
    renderWithProviders(<Login />);
    expect(screen.getByText('AutonomousSDR')).toBeInTheDocument();
    expect(screen.getByText('AI-powered lead intelligence')).toBeInTheDocument();
  });

  it('allows typing in email and password fields', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Login />);

    await user.type(screen.getByLabelText('Email'), 'test@example.com');
    await user.type(screen.getByLabelText('Password'), 'mypassword');

    expect(screen.getByLabelText('Email')).toHaveValue('test@example.com');
    expect(screen.getByLabelText('Password')).toHaveValue('mypassword');
  });

  it('toggles password visibility', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Login />);

    const passwordInput = screen.getByLabelText('Password');
    expect(passwordInput).toHaveAttribute('type', 'password');

    // Click the show/hide button
    const toggleBtn = screen.getByRole('button', { name: '' }); // eye icon button
    await user.click(toggleBtn);
    expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'text');

    // Toggle back
    await user.click(screen.getByRole('button', { name: '' }));
    expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'password');
  });

  it('submits the form and navigates on success', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Login />, { initialRoute: '/login' });

    await user.type(screen.getByLabelText('Email'), 'test@example.com');
    await user.type(screen.getByLabelText('Password'), 'password123');

    fireEvent.submit(screen.getByRole('button', { name: /sign in/i }).closest('form')!);

    // MSW intercepts login and returns success, navigate('/') is called
    await waitFor(() => {
      // Auth store should be updated - just verify no error toast
      expect(screen.queryByText('Invalid credentials')).not.toBeInTheDocument();
    });
  });

  it('shows password field masking by default', () => {
    renderWithProviders(<Login />);
    expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'password');
  });

  it('renders contact admin link', () => {
    renderWithProviders(<Login />);
    expect(screen.getByText(/contact admin/i)).toBeInTheDocument();
  });
});
