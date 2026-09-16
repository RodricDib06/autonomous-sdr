import { describe, it, expect, afterEach } from 'vitest';
import { screen, waitFor, fireEvent, render } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { renderWithProviders } from '../utils';
import Login from '../../pages/Login';
import App from '../../App';
import { authApi } from '../../lib/api';
import { server } from '../mocks/server';

afterEach(() => {
  server.resetHandlers();
});

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

  it('clicking Contact admin link shows info toast', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Login />);
    await user.click(screen.getByText(/contact admin/i));
    await waitFor(() => {
      expect(screen.getByText(/Contact your administrator/i)).toBeInTheDocument();
    });
  });

  it('shows error toast when login fails with API error', async () => {
    server.use(
      http.post('http://localhost:8000/auth/login', () =>
        HttpResponse.json({ detail: 'Incorrect email or password' }, { status: 401 })
      )
    );
    const user = userEvent.setup();
    renderWithProviders(<Login />);

    await user.type(screen.getByLabelText('Email'), 'wrong@example.com');
    await user.type(screen.getByLabelText('Password'), 'wrongpassword');
    fireEvent.submit(screen.getByRole('button', { name: /sign in/i }).closest('form')!);

    await waitFor(() => {
      expect(screen.getByText(/Incorrect email or password/i)).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('shows generic error toast when login fails without API message', async () => {
    server.use(
      http.post('http://localhost:8000/auth/login', () =>
        HttpResponse.json({}, { status: 500 })
      )
    );
    const user = userEvent.setup();
    renderWithProviders(<Login />);

    await user.type(screen.getByLabelText('Email'), 'test@example.com');
    await user.type(screen.getByLabelText('Password'), 'password123');
    fireEvent.submit(screen.getByRole('button', { name: /sign in/i }).closest('form')!);

    await waitFor(() => {
      expect(screen.getByText(/Invalid credentials/i)).toBeInTheDocument();
    }, { timeout: 3000 });
  });
});

describe('Login feedback in the real App tree', () => {
  // The shared test wrapper mounts its own <Toaster />, so every other test
  // here sees toasts that production did not have: the Toaster used to live
  // in Layout, which wraps only authenticated routes. A failed sign-in on
  // /login therefore rendered nothing at all. Render App itself so the
  // assertion depends on where the Toaster is actually mounted.
  it('shows an error when credentials are rejected', async () => {
    server.use(
      http.post('http://localhost:8000/auth/login', () =>
        HttpResponse.json({ detail: 'Incorrect email or password' }, { status: 401 })
      )
    );

    window.history.pushState({}, '', '/login');
    render(<App />);

    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Email'), 'admin@autonomoussdr.com');
    await user.type(screen.getByLabelText('Password'), 'wrong-password');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    expect(await screen.findByText(/incorrect email or password/i, {}, { timeout: 5000 })).toBeInTheDocument();
  });
});

describe('401 handling on the sign-in request', () => {
  // jsdom cannot actually navigate — it only warns — so the App-level test
  // above still renders a toast even when the interceptor tries to reload.
  // In a real browser that reload wipes the page. Assert the navigation is
  // never attempted rather than relying on what jsdom happens to do.
  it('does not treat rejected credentials as an expired session', async () => {
    server.use(
      http.post('http://localhost:8000/auth/login', () =>
        HttpResponse.json({ detail: 'Incorrect email or password' }, { status: 401 })
      )
    );

    const realLocation = window.location;
    const assigned: string[] = [];
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: Object.defineProperty({ ...realLocation }, 'href', {
        get: () => realLocation.href,
        set: (v: string) => { assigned.push(v); },
      }),
    });

    try {
      localStorage.removeItem('refresh_token');
      await expect(authApi.login('admin@autonomoussdr.com', 'wrong')).rejects.toBeDefined();
      expect(assigned).toEqual([]);
    } finally {
      Object.defineProperty(window, 'location', { configurable: true, value: realLocation });
    }
  });
});
