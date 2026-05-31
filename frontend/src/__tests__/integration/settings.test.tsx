import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../utils';
import Settings from '../../pages/Settings';
import { useAuthStore } from '../../store/authStore';
import { mockUser } from '../mocks/handlers';

beforeEach(() => {
  useAuthStore.setState({ user: mockUser, accessToken: 'tok', refreshToken: 'ref' });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Settings page', () => {
  it('renders the page header', () => {
    renderWithProviders(<Settings />);
    expect(screen.getByText('Settings')).toBeInTheDocument();
  });

  it('renders Slack notifications section', async () => {
    renderWithProviders(<Settings />);
    await waitFor(() => {
      expect(screen.getByText('Slack Notifications')).toBeInTheDocument();
    });
  });

  it('renders API Keys section', async () => {
    renderWithProviders(<Settings />);
    await waitFor(() => {
      expect(screen.getByText('API Keys')).toBeInTheDocument();
    });
  });

  it('shows new key button', async () => {
    renderWithProviders(<Settings />);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /new key/i })).toBeInTheDocument();
    });
  });

  it('shows slack webhook input when not configured', async () => {
    renderWithProviders(<Settings />);
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/https:\/\/hooks.slack.com/i)).toBeInTheDocument();
    });
  });

  it('Save Webhook button is disabled when input is empty', async () => {
    renderWithProviders(<Settings />);
    await waitFor(() => screen.getByPlaceholderText(/https:\/\/hooks.slack.com/i));
    expect(screen.getByRole('button', { name: /save webhook/i })).toBeDisabled();
  });

  it('enables Save Webhook when valid URL is typed', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Settings />);
    await waitFor(() => screen.getByPlaceholderText(/https:\/\/hooks.slack.com/i));

    await user.type(
      screen.getByPlaceholderText(/https:\/\/hooks.slack.com/i),
      'https://hooks.slack.com/services/ABC/DEF/xyz'
    );

    expect(screen.getByRole('button', { name: /save webhook/i })).not.toBeDisabled();
  });

  it('clicking Save Webhook fires the mutation', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Settings />);
    await waitFor(() => screen.getByPlaceholderText(/https:\/\/hooks.slack.com/i));

    await user.type(
      screen.getByPlaceholderText(/https:\/\/hooks.slack.com/i),
      'https://hooks.slack.com/services/ABC/DEF/xyz'
    );

    await user.click(screen.getByRole('button', { name: /save webhook/i }));
    // MSW returns { enabled: true } — input should clear after success
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/https:\/\/hooks.slack.com/i)).toHaveValue('');
    });
  });

  it('shows webhook help text', async () => {
    renderWithProviders(<Settings />);
    await waitFor(() => {
      expect(screen.getByText(/Incoming Webhooks/i)).toBeInTheDocument();
    });
  });

  it('shows Not connected badge when slack not configured', async () => {
    renderWithProviders(<Settings />);
    await waitFor(() => {
      expect(screen.getByText(/not connected/i)).toBeInTheDocument();
    });
  });

  it('opens New Key dialog on button click', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Settings />);
    await waitFor(() => screen.getByRole('button', { name: /new key/i }));

    await user.click(screen.getByRole('button', { name: /new key/i }));

    await waitFor(() => {
      expect(screen.getByText('Create API Key')).toBeInTheDocument();
      expect(screen.getByText(/shown only once/i)).toBeInTheDocument();
    });
  });

  it('can type a key name in the dialog', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Settings />);
    await waitFor(() => screen.getByRole('button', { name: /new key/i }));

    await user.click(screen.getByRole('button', { name: /new key/i }));
    await waitFor(() => screen.getByText('Key Name'));

    const nameInput = screen.getByRole('textbox');
    await user.type(nameInput, 'My Test Key');
    expect(nameInput).toHaveValue('My Test Key');
  });

  it('submitting the dialog creates key and shows revealed key dialog', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Settings />);
    await waitFor(() => screen.getByRole('button', { name: /new key/i }));

    await user.click(screen.getByRole('button', { name: /new key/i }));
    await waitFor(() => screen.getByText('Key Name'));

    await user.type(screen.getByRole('textbox'), 'Production Key');
    await user.click(screen.getByRole('button', { name: /^create key$/i }));

    // MSW returns the key; revealed key dialog shows
    await waitFor(() => {
      expect(screen.getByText('API Key Created')).toBeInTheDocument();
    });
  });

  it('revealed key dialog shows the full key from MSW', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Settings />);
    await waitFor(() => screen.getByRole('button', { name: /new key/i }));
    await user.click(screen.getByRole('button', { name: /new key/i }));
    await waitFor(() => screen.getByText('Key Name'));
    await user.type(screen.getByRole('textbox'), 'My Key');
    await user.click(screen.getByRole('button', { name: /^create key$/i }));

    await waitFor(() => screen.getByText('API Key Created'));
    // The mock key value sk_test_full_key should be visible
    expect(screen.getByText('sk_test_full_key')).toBeInTheDocument();
  });

  it('revealed key dialog has a Done button that closes it', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Settings />);
    await waitFor(() => screen.getByRole('button', { name: /new key/i }));
    await user.click(screen.getByRole('button', { name: /new key/i }));
    await waitFor(() => screen.getByText('Key Name'));
    await user.type(screen.getByRole('textbox'), 'My Key');
    await user.click(screen.getByRole('button', { name: /^create key$/i }));

    await waitFor(() => screen.getByText('API Key Created'));
    await user.click(screen.getByRole('button', { name: /done/i }));

    await waitFor(() => {
      expect(screen.queryByText('API Key Created')).not.toBeInTheDocument();
    });
  });

  it('renders profile card with user email', async () => {
    renderWithProviders(<Settings />);
    await waitFor(() => {
      expect(screen.getByText('test@example.com')).toBeInTheDocument();
    });
  });

  it('shows Change Password section', () => {
    renderWithProviders(<Settings />);
    expect(screen.getByText('Change Password')).toBeInTheDocument();
  });

  it('shows password fields in Change Password section', () => {
    renderWithProviders(<Settings />);
    expect(screen.getByText('Current Password')).toBeInTheDocument();
    expect(screen.getByText('New Password')).toBeInTheDocument();
  });

  it('shows Update Password button', () => {
    renderWithProviders(<Settings />);
    expect(screen.getByRole('button', { name: /update password/i })).toBeInTheDocument();
  });

  it('password show/hide toggle changes input type', async () => {
    const user = userEvent.setup();
    const { container } = renderWithProviders(<Settings />);

    // Both password inputs default to type="password"
    const passwordInputs = container.querySelectorAll('input[type="password"]');
    expect(passwordInputs.length).toBeGreaterThanOrEqual(2);

    // Click the eye toggle button (in the New Password field)
    const eyeBtn = container.querySelector('form button[type="button"]') as HTMLElement;
    await user.click(eyeBtn);

    // After toggle, inputs switch to type="text"
    const textInputs = container.querySelectorAll('input[type="text"]');
    expect(textInputs.length).toBeGreaterThan(0);
  });

  it('shows empty API keys message when no keys exist', async () => {
    renderWithProviders(<Settings />);
    await waitFor(() => {
      expect(screen.getByText(/No API keys yet/i)).toBeInTheDocument();
    });
  });

  it('Cancel button in New Key dialog closes dialog', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Settings />);
    await waitFor(() => screen.getByRole('button', { name: /new key/i }));
    await user.click(screen.getByRole('button', { name: /new key/i }));
    await waitFor(() => screen.getByText('Create API Key'));

    await user.click(screen.getByRole('button', { name: /^cancel$/i }));

    await waitFor(() => {
      expect(screen.queryByText('Create API Key')).not.toBeInTheDocument();
    });
  });
});
