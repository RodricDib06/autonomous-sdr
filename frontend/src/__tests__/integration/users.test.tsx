import { describe, it, expect, vi, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../utils';
import Users from '../../pages/Users';

afterEach(() => {
  vi.unstubAllGlobals();
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
});
