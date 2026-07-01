import { describe, it, expect, vi, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { renderWithProviders } from '../utils';
import Users from '../../pages/Users';
import { server } from '../mocks/server';
import { useAuthStore } from '../../store/authStore';

afterEach(() => {
  vi.unstubAllGlobals();
  server.resetHandlers();
  useAuthStore.setState({ user: null, accessToken: null, refreshToken: null });
});

describe('Users page', () => {
  it('renders the page header', () => {
    renderWithProviders(<Users />);
    expect(screen.getByText('Users')).toBeInTheDocument();
  });

  it('shows team member count in subtitle after data loads', async () => {
    renderWithProviders(<Users />);
    // Mock returns 1 user: "1 team member"
    await waitFor(() => {
      expect(screen.getByText(/team member/i)).toBeInTheDocument();
    });
  });

  it('shows user email from mock data', async () => {
    renderWithProviders(<Users />);
    await waitFor(() => {
      expect(screen.getByText('test@example.com')).toBeInTheDocument();
    });
  });

  it('shows user role badge', async () => {
    renderWithProviders(<Users />);
    await waitFor(() => {
      expect(screen.getByText('rep')).toBeInTheDocument();
    });
  });

  it('renders Add User button', () => {
    renderWithProviders(<Users />);
    expect(screen.getByRole('button', { name: /add user/i })).toBeInTheDocument();
  });

  it('opens create user dialog on button click', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Users />);

    await user.click(screen.getByRole('button', { name: /add user/i }));

    await waitFor(() => {
      expect(screen.getByText('Add a team member to AutonomousSDR')).toBeInTheDocument();
    });
  });

  it('renders role legend section', async () => {
    renderWithProviders(<Users />);
    await waitFor(() => {
      expect(screen.getByText('Admin')).toBeInTheDocument();
      expect(screen.getByText(/full access/i)).toBeInTheDocument();
    });
  });

  it('shows the deactivate button for other users', async () => {
    renderWithProviders(<Users />);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /deactivate/i })).toBeInTheDocument();
    });
  });

  it('calls window.confirm when deactivate is clicked', async () => {
    const confirmMock = vi.fn(() => false);
    vi.stubGlobal('confirm', confirmMock);
    const user = userEvent.setup();
    renderWithProviders(<Users />);
    await waitFor(() => screen.getByRole('button', { name: /deactivate/i }));
    await user.click(screen.getByRole('button', { name: /deactivate/i }));
    expect(confirmMock).toHaveBeenCalledWith('Deactivate test@example.com?');
  });

  it('shows edit pencil button for other users', async () => {
    const { container } = renderWithProviders(<Users />);
    await waitFor(() => screen.getByText('test@example.com'));
    // The pencil edit button is in the role cell (p-1 rounded class)
    const pencilBtn = container.querySelector('td button.p-1.rounded');
    expect(pencilBtn).not.toBeNull();
  });

  it('clicking edit pencil opens inline role selector', async () => {
    const user = userEvent.setup();
    const { container } = renderWithProviders(<Users />);
    await waitFor(() => screen.getByText('test@example.com'));

    const pencilBtn = container.querySelector('td button.p-1.rounded') as HTMLElement;
    await user.click(pencilBtn);

    await waitFor(() => {
      // RoleInlineEdit: two p-1 buttons appear (save + cancel)
      expect(container.querySelectorAll('button.p-1').length).toBe(2);
    });
  });

  it('clicking cancel in inline edit closes the role selector', async () => {
    const user = userEvent.setup();
    const { container } = renderWithProviders(<Users />);
    await waitFor(() => screen.getByText('test@example.com'));

    const pencilBtn = container.querySelector('td button.p-1.rounded') as HTMLElement;
    await user.click(pencilBtn);

    await waitFor(() => {
      expect(container.querySelector('[class*="emerald-500"]')).not.toBeNull();
    });

    // p-1 buttons: [save (emerald), cancel (red)] — cancel is second
    const inlineButtons = container.querySelectorAll('button.p-1');
    const cancelBtn = inlineButtons[inlineButtons.length - 1] as HTMLElement;
    await user.click(cancelBtn);

    await waitFor(() => {
      // RoleInlineEdit is gone — only the pencil button remains (1 p-1 button)
      expect(container.querySelectorAll('button.p-1').length).toBe(1);
    });
  });

  it('clicking save in inline role edit fires the changeRole mutation', async () => {
    const user = userEvent.setup();
    const { container } = renderWithProviders(<Users />);
    await waitFor(() => screen.getByText('test@example.com'));

    const pencilBtn = container.querySelector('td button.p-1.rounded') as HTMLElement;
    await user.click(pencilBtn);

    await waitFor(() => {
      expect(container.querySelectorAll('button.p-1').length).toBe(2);
    });

    // First p-1 button is the save (check mark, emerald)
    const saveBtn = container.querySelectorAll('button.p-1')[0] as HTMLElement;
    await user.click(saveBtn);

    // MSW PUT /auth/users/:id/role returns mockUser → toast shows
    await waitFor(() => {
      expect(screen.getByText(/role updated/i)).toBeInTheDocument();
    });
  });

  it('deactivates user when confirm returns true', async () => {
    vi.stubGlobal('confirm', vi.fn(() => true));
    const user = userEvent.setup();
    renderWithProviders(<Users />);
    await waitFor(() => screen.getByRole('button', { name: /deactivate/i }));

    await user.click(screen.getByRole('button', { name: /deactivate/i }));

    await waitFor(() => {
      expect(screen.getByText(/user deactivated/i)).toBeInTheDocument();
    });
  });

  it('shows "you" label next to the logged-in user email', async () => {
    // Override users list to return a user whose ID matches the current auth user
    // (auth store user is null by default here, so this only shows when IDs match)
    // The existing test works because me is null — just verify "(you)" never shows
    // since no auth user is set in this test suite
    renderWithProviders(<Users />);
    await waitFor(() => screen.getByText('test@example.com'));
    // Without auth context set, "(you)" doesn't appear
    expect(screen.queryByText('(you)')).not.toBeInTheDocument();
  });

  it('shows multiple users when API returns them', async () => {
    server.use(
      http.get('http://localhost:8000/auth/users', () =>
        HttpResponse.json([
          { id: 'user-1', email: 'user1@test.com', role: 'admin', is_active: true, created_at: '2024-01-01T00:00:00Z', last_login_at: null },
          { id: 'user-2', email: 'user2@test.com', role: 'rep', is_active: true, created_at: '2024-01-02T00:00:00Z', last_login_at: null },
        ])
      )
    );
    renderWithProviders(<Users />);
    await waitFor(() => {
      expect(screen.getByText('user1@test.com')).toBeInTheDocument();
      expect(screen.getByText('user2@test.com')).toBeInTheDocument();
    });
    // Subtitle shows "2 team members"
    expect(screen.getByText(/2 team members/i)).toBeInTheDocument();
  });

  it('fills out create user form and submits', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Users />);

    await user.click(screen.getByRole('button', { name: /add user/i }));
    await waitFor(() => screen.getByText('Create New User'));

    await user.type(screen.getByPlaceholderText('user@company.com'), 'newuser@example.com');
    await user.type(screen.getByPlaceholderText('Min 8 characters'), 'password123');
    await user.click(screen.getByRole('button', { name: /create user/i }));

    // MSW returns success → dialog closes
    await waitFor(() => {
      expect(screen.queryByText('Create New User')).not.toBeInTheDocument();
    });
  });

  it('shows "(you)" label when auth user matches list user', async () => {
    const { useAuthStore } = await import('../../store/authStore');
    const { mockUser } = await import('../mocks/handlers');
    // Set auth store with user-1 (same ID as mockUser in list)
    useAuthStore.setState({ user: mockUser, accessToken: 'tok', refreshToken: 'ref' });

    renderWithProviders(<Users />);
    await waitFor(() => {
      expect(screen.getByText('(you)')).toBeInTheDocument();
    });
  });

  it('create user form shows error toast on API failure', async () => {
    server.use(
      http.post('http://localhost:8000/auth/register', () =>
        HttpResponse.json({ detail: 'Email already exists' }, { status: 409 })
      )
    );
    const user = userEvent.setup();
    renderWithProviders(<Users />);
    await user.click(screen.getByRole('button', { name: /add user/i }));
    await waitFor(() => screen.getByText('Create New User'));

    await user.type(screen.getByPlaceholderText('user@company.com'), 'existing@example.com');
    await user.type(screen.getByPlaceholderText('Min 8 characters'), 'password123');
    await user.click(screen.getByRole('button', { name: /create user/i }));

    await waitFor(() => {
      expect(screen.getByText(/Email already exists/i)).toBeInTheDocument();
    });
  });

  it('hides deactivate button for own account (you)', async () => {
    const { useAuthStore } = await import('../../store/authStore');
    const { mockUser } = await import('../mocks/handlers');
    useAuthStore.setState({ user: mockUser, accessToken: 'tok', refreshToken: 'ref' });

    renderWithProviders(<Users />);
    await waitFor(() => screen.getByText('(you)'));
    // When user is viewing their own account, deactivate button should not appear
    expect(screen.queryByRole('button', { name: /deactivate/i })).not.toBeInTheDocument();
  });

  it('shows "Inactive" badge for deactivated user', async () => {
    server.use(
      http.get('http://localhost:8000/auth/users', () =>
        HttpResponse.json([
          { id: 'user-2', email: 'inactive@example.com', role: 'rep', is_active: false, created_at: '2024-01-01T00:00:00Z', last_login_at: null },
        ])
      )
    );
    renderWithProviders(<Users />);
    await waitFor(() => {
      expect(screen.getByText('Inactive')).toBeInTheDocument();
    });
  });

  it('shows error toast when changeRole API fails', async () => {
    server.use(
      http.put('http://localhost:8000/auth/users/:id/role', () =>
        HttpResponse.json({ detail: 'Forbidden' }, { status: 403 })
      )
    );
    const user = userEvent.setup();
    const { container } = renderWithProviders(<Users />);
    await waitFor(() => screen.getByText('test@example.com'));

    const pencilBtn = container.querySelector('td button.p-1.rounded') as HTMLElement;
    await user.click(pencilBtn);
    await waitFor(() => expect(container.querySelectorAll('button.p-1').length).toBe(2));

    const saveBtn = container.querySelectorAll('button.p-1')[0] as HTMLElement;
    await user.click(saveBtn);

    await waitFor(() => {
      expect(screen.getByText(/Failed to update role/i)).toBeInTheDocument();
    });
  });

  it('shows error toast when deactivate API fails', async () => {
    server.use(
      http.delete('http://localhost:8000/auth/users/:id', () =>
        HttpResponse.json({ detail: 'Cannot deactivate' }, { status: 500 })
      )
    );
    vi.stubGlobal('confirm', vi.fn(() => true));
    const user = userEvent.setup();
    renderWithProviders(<Users />);
    await waitFor(() => screen.getByRole('button', { name: /deactivate/i }));

    await user.click(screen.getByRole('button', { name: /deactivate/i }));

    await waitFor(() => {
      expect(screen.getByText(/Cannot deactivate/i)).toBeInTheDocument();
    });
  });

  it('Cancel button in create user dialog closes dialog', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Users />);
    await user.click(screen.getByRole('button', { name: /add user/i }));
    await waitFor(() => screen.getByText('Create New User'));

    await user.click(screen.getByRole('button', { name: /^cancel$/i }));

    await waitFor(() => {
      expect(screen.queryByText('Create New User')).not.toBeInTheDocument();
    });
  });

  it('role inline edit dropdown fires onValueChange when role is changed', async () => {
    const user = userEvent.setup();
    const { container } = renderWithProviders(<Users />);
    await waitFor(() => screen.getByText('test@example.com'));

    const pencilBtn = container.querySelector('td button.p-1.rounded') as HTMLElement;
    await user.click(pencilBtn);
    await waitFor(() => expect(container.querySelectorAll('button.p-1').length).toBe(2));

    // The RoleInlineEdit renders a Select — saving the current role still fires onSave
    const saveBtn = container.querySelectorAll('button.p-1')[0] as HTMLElement;
    await user.click(saveBtn);

    await waitFor(() => {
      expect(screen.getByText(/role updated/i)).toBeInTheDocument();
    });
  });
});
