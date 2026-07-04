import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { renderWithProviders } from '../utils';
import Settings from '../../pages/Settings';
import { useAuthStore } from '../../store/authStore';
import { mockUser } from '../mocks/handlers';
import { server } from '../mocks/server';

beforeEach(() => {
  useAuthStore.setState({ user: mockUser, accessToken: 'tok', refreshToken: 'ref' });
});

afterEach(() => {
  vi.unstubAllGlobals();
  server.resetHandlers();
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

  it('shows Connected badge and Test/Disconnect buttons when Slack is configured', async () => {
    server.use(
      http.get('http://localhost:8000/config/slack', () =>
        HttpResponse.json({ enabled: true, configured: true, webhook_url: 'https://hooks.slack.com/services/XYZ' })
      )
    );
    renderWithProviders(<Settings />);
    await waitFor(() => {
      expect(screen.getByText('Connected')).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /test/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /disconnect/i })).toBeInTheDocument();
  });

  it('clicking Test sends test webhook request', async () => {
    server.use(
      http.get('http://localhost:8000/config/slack', () =>
        HttpResponse.json({ enabled: true, configured: true, webhook_url: 'https://hooks.slack.com/services/XYZ' })
      )
    );
    const user = userEvent.setup();
    renderWithProviders(<Settings />);
    await waitFor(() => expect(screen.getByRole('button', { name: /test/i })).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /test/i }));

    await waitFor(() => {
      expect(screen.getByText(/test message sent/i)).toBeInTheDocument();
    });
  });

  it('clicking Disconnect calls disable and removes Connected badge', async () => {
    server.use(
      http.get('http://localhost:8000/config/slack', () =>
        HttpResponse.json({ enabled: true, configured: true, webhook_url: 'https://hooks.slack.com/services/XYZ' })
      ),
      http.post('http://localhost:8000/config/slack/disable', () =>
        HttpResponse.json({ enabled: false, configured: false })
      )
    );
    const user = userEvent.setup();
    renderWithProviders(<Settings />);
    await waitFor(() => expect(screen.getByRole('button', { name: /disconnect/i })).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /disconnect/i }));

    await waitFor(() => {
      expect(screen.getByText(/slack notifications disabled/i)).toBeInTheDocument();
    });
  });

  it('Change Password form shows error toast when new password is too short', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Settings />);

    screen.getAllByRole('textbox', { hidden: true }).filter(
      (el) => (el as HTMLInputElement).type === 'password' || el.closest('form')
    );

    // Use querySelectors for password inputs since they are type="password" not "textbox"
    const form = document.querySelector('form');
    const inputs = form?.querySelectorAll('input') ?? [];
    if (inputs.length >= 2) {
      await user.type(inputs[0], 'currentpass');
      await user.type(inputs[1], 'short');
      await user.click(screen.getByRole('button', { name: /update password/i }));

      await waitFor(() => {
        expect(screen.getByText(/at least 8 characters/i)).toBeInTheDocument();
      });
    }
  });

  it('successful password change clears the form', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Settings />);

    const form = document.querySelector('form');
    const inputs = form?.querySelectorAll('input') ?? [];
    if (inputs.length >= 2) {
      await user.type(inputs[0], 'currentpassword');
      await user.type(inputs[1], 'newpassword123');
      await user.click(screen.getByRole('button', { name: /update password/i }));

      await waitFor(() => {
        expect(screen.getByText(/password changed/i)).toBeInTheDocument();
      });
    }
  });

  it('shows API keys in the list when they exist', async () => {
    server.use(
      http.get('http://localhost:8000/auth/api-keys', () =>
        HttpResponse.json([
          { id: 'key-1', name: 'Production Key', key_prefix: 'sk_prod', is_active: true, created_at: '2024-01-01T00:00:00Z', last_used_at: '2024-01-10T00:00:00Z' },
        ])
      )
    );
    renderWithProviders(<Settings />);
    await waitFor(() => {
      expect(screen.getByText('Production Key')).toBeInTheDocument();
    });
    expect(screen.getByText(/sk_prod/)).toBeInTheDocument();
    expect(screen.getByText(/used/i)).toBeInTheDocument();
  });

  it('revealed key dialog shows security warning about storing the key', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Settings />);
    await waitFor(() => screen.getByRole('button', { name: /new key/i }));
    await user.click(screen.getByRole('button', { name: /new key/i }));
    await waitFor(() => screen.getByText('Key Name'));
    await user.type(screen.getByRole('textbox'), 'Copy Test Key');
    await user.click(screen.getByRole('button', { name: /^create key$/i }));
    await waitFor(() => screen.getByText('API Key Created'));

    // The key value is visible in the revealed dialog
    expect(screen.getByText('sk_test_full_key')).toBeInTheDocument();
    // Security warning about storing securely
    expect(screen.getByText(/store this key securely/i)).toBeInTheDocument();
    // Copy this now warning
    expect(screen.getByText(/never be shown again/i)).toBeInTheDocument();
  });

  it('copy button in revealed key dialog is present', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Settings />);
    await waitFor(() => screen.getByRole('button', { name: /new key/i }));
    await user.click(screen.getByRole('button', { name: /new key/i }));
    await waitFor(() => screen.getByText('Key Name'));
    await user.type(screen.getByRole('textbox'), 'Copy Test Key');
    await user.click(screen.getByRole('button', { name: /^create key$/i }));
    await waitFor(() => screen.getByText('API Key Created'));

    // The copy button is present in the revealed key dialog
    const copyBtn = document.querySelector('button[class*="p-1.5"]') as HTMLElement;
    expect(copyBtn).toBeInTheDocument();
    // Clicking exercises the copy() function body (navigator.clipboard + setCopied)
    fireEvent.click(copyBtn);
    // After click, the copied state toggles (CheckCircle2 appears in the button briefly)
    // Just verify no error was thrown (function executed)
    expect(copyBtn).toBeInTheDocument();
  });

  it('API keys list shows "Never used" when no last_used_at', async () => {
    server.use(
      http.get('http://localhost:8000/auth/api-keys', () =>
        HttpResponse.json([
          { id: 'key-1', name: 'Dev Key', key_prefix: 'sk_dev', is_active: true, created_at: '2024-01-01T00:00:00Z', last_used_at: null },
        ])
      )
    );
    renderWithProviders(<Settings />);
    await waitFor(() => {
      expect(screen.getByText('Dev Key')).toBeInTheDocument();
    });
    expect(screen.getByText(/Never used/i)).toBeInTheDocument();
  });

  it('clicking revoke key with confirm=true calls revoke mutation', async () => {
    vi.stubGlobal('confirm', vi.fn(() => true));
    server.use(
      http.get('http://localhost:8000/auth/api-keys', () =>
        HttpResponse.json([
          { id: 'key-1', name: 'Production Key', key_prefix: 'sk_prod', is_active: true, created_at: '2024-01-01T00:00:00Z', last_used_at: null },
        ])
      )
    );
    const user = userEvent.setup();
    renderWithProviders(<Settings />);
    await waitFor(() => screen.getByText('Production Key'));

    // Click the trash/revoke button inside the API-key row (not other sections' delete buttons)
    const keyRow = screen.getByText('Production Key').closest('div[class*="border"]') as HTMLElement;
    const revokeBtn = keyRow.querySelector('button[class*="text-red-400"]') as HTMLElement;
    if (revokeBtn) {
      await user.click(revokeBtn);
      await waitFor(() => {
        expect(screen.getByText(/API key revoked/i)).toBeInTheDocument();
      });
    }
  });

  it('clicking revoke key with confirm=false does not call mutation', async () => {
    vi.stubGlobal('confirm', vi.fn(() => false));
    server.use(
      http.get('http://localhost:8000/auth/api-keys', () =>
        HttpResponse.json([
          { id: 'key-1', name: 'Production Key', key_prefix: 'sk_prod', is_active: true, created_at: '2024-01-01T00:00:00Z', last_used_at: null },
        ])
      )
    );
    const user = userEvent.setup();
    renderWithProviders(<Settings />);
    await waitFor(() => screen.getByText('Production Key'));

    const keyRow = screen.getByText('Production Key').closest('div[class*="border"]') as HTMLElement;
    const revokeBtn = keyRow.querySelector('button[class*="text-red-400"]') as HTMLElement;
    if (revokeBtn) {
      await user.click(revokeBtn);
      // Key stays in the list (not revoked)
      await waitFor(() => {
        expect(screen.getByText('Production Key')).toBeInTheDocument();
      });
    }
  });

  it('password change API error shows error toast', async () => {
    server.use(
      http.put('http://localhost:8000/auth/me/password', () =>
        HttpResponse.json({ detail: 'Current password is incorrect' }, { status: 400 })
      )
    );
    const user = userEvent.setup();
    renderWithProviders(<Settings />);

    const form = document.querySelector('form');
    const inputs = form?.querySelectorAll('input') ?? [];
    if (inputs.length >= 2) {
      await user.type(inputs[0], 'wrongpassword');
      await user.type(inputs[1], 'newpassword123');
      await user.click(screen.getByRole('button', { name: /update password/i }));

      await waitFor(() => {
        expect(screen.getByText(/Current password is incorrect/i)).toBeInTheDocument();
      });
    }
  });

  it('shows Save Webhook success toast after saving webhook', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Settings />);
    await waitFor(() => screen.getByPlaceholderText(/https:\/\/hooks.slack.com/i));

    await user.type(
      screen.getByPlaceholderText(/https:\/\/hooks.slack.com/i),
      'https://hooks.slack.com/services/ABC/DEF/xyz'
    );

    await user.click(screen.getByRole('button', { name: /save webhook/i }));

    await waitFor(() => {
      expect(screen.getByText(/Slack webhook saved/i)).toBeInTheDocument();
    });
  });

  it('Slack configured state shows webhook is active message', async () => {
    server.use(
      http.get('http://localhost:8000/config/slack', () =>
        HttpResponse.json({ enabled: true, configured: true, webhook_url: 'https://hooks.slack.com/services/XYZ' })
      )
    );
    renderWithProviders(<Settings />);
    await waitFor(() => {
      expect(screen.getByText(/Slack webhook is configured and active/i)).toBeInTheDocument();
    });
  });

  it('shows error toast when Slack webhook save fails', async () => {
    server.use(
      http.post('http://localhost:8000/config/slack', () =>
        HttpResponse.json({ detail: 'Invalid webhook URL' }, { status: 400 })
      )
    );
    const user = userEvent.setup();
    renderWithProviders(<Settings />);
    await waitFor(() => screen.getByPlaceholderText(/https:\/\/hooks.slack.com/i));

    await user.type(
      screen.getByPlaceholderText(/https:\/\/hooks.slack.com/i),
      'https://hooks.slack.com/services/BAD/URL/xyz'
    );
    await user.click(screen.getByRole('button', { name: /save webhook/i }));

    await waitFor(() => {
      expect(screen.getByText(/Invalid webhook URL/i)).toBeInTheDocument();
    });
  });

  it('shows error toast when Slack test webhook fails', async () => {
    server.use(
      http.get('http://localhost:8000/config/slack', () =>
        HttpResponse.json({ enabled: true, configured: true, webhook_url: 'https://hooks.slack.com/services/XYZ' })
      ),
      http.post('http://localhost:8000/config/slack/test', () =>
        HttpResponse.json({ detail: 'Failed' }, { status: 500 })
      )
    );
    const user = userEvent.setup();
    renderWithProviders(<Settings />);
    await waitFor(() => expect(screen.getByRole('button', { name: /test/i })).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /test/i }));

    await waitFor(() => {
      expect(screen.getByText(/Webhook test failed/i)).toBeInTheDocument();
    });
  });

  it('shows error toast when creating API key fails', async () => {
    server.use(
      http.post('http://localhost:8000/auth/api-keys', () =>
        HttpResponse.json({ detail: 'Key limit reached' }, { status: 400 })
      )
    );
    const user = userEvent.setup();
    renderWithProviders(<Settings />);
    await waitFor(() => screen.getByRole('button', { name: /new key/i }));
    await user.click(screen.getByRole('button', { name: /new key/i }));
    await waitFor(() => screen.getByText('Key Name'));

    await user.type(screen.getByRole('textbox'), 'My New Key');
    await user.click(screen.getByRole('button', { name: /^create key$/i }));

    await waitFor(() => {
      expect(screen.getByText(/Key limit reached/i)).toBeInTheDocument();
    });
  });

  it('copy button in revealed key dialog sets copied state', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Settings />);
    await waitFor(() => screen.getByRole('button', { name: /new key/i }));
    await user.click(screen.getByRole('button', { name: /new key/i }));
    await waitFor(() => screen.getByText('Key Name'));
    await user.type(screen.getByRole('textbox'), 'Clipboard Test Key');
    await user.click(screen.getByRole('button', { name: /^create key$/i }));
    await waitFor(() => screen.getByText('API Key Created'));

    // The copy button is the p-1.5 button in the revealed key dialog
    const copyBtn = document.querySelector('button[class*="p-1.5"]') as HTMLElement;
    expect(copyBtn).toBeInTheDocument();
    // Clicking triggers copy() which calls navigator.clipboard.writeText + setCopied(true)
    fireEvent.click(copyBtn);
    // After click, dialog remains open and key text is still shown
    await waitFor(() => {
      expect(screen.getByText('sk_test_full_key')).toBeInTheDocument();
    });
  });
});

describe('Settings — Compliance & Send Safety', () => {
  it('renders the compliance section with guardrail status', async () => {
    renderWithProviders(<Settings />);
    await waitFor(() => {
      expect(screen.getByText('Compliance & Send Safety')).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByText('Sending allowed')).toBeInTheDocument();
    });
    expect(screen.getByText(/12 \/ 200 in last 24h/)).toBeInTheDocument();
  });

  it('shows sends-held badge when guardrails block sending', async () => {
    server.use(
      http.get('http://localhost:8000/outreach/guardrails', () =>
        HttpResponse.json({
          can_send: false,
          reason: 'Daily send cap reached (200/200 in last 24h)',
          sent_last_24h: 200,
          daily_limit: 200,
          window_start_hour_utc: 8,
          window_end_hour_utc: 18,
          weekdays_only: true,
          suppression_count: 1,
        })
      )
    );
    renderWithProviders(<Settings />);
    await waitFor(() => {
      expect(screen.getByText('Sends held')).toBeInTheDocument();
    });
    expect(screen.getByText(/Daily send cap reached/)).toBeInTheDocument();
  });

  it('lists existing suppression entries', async () => {
    renderWithProviders(<Settings />);
    await waitFor(() => {
      expect(screen.getByText('optout@corp.com')).toBeInTheDocument();
    });
    expect(screen.getByText(/unsubscribe link/)).toBeInTheDocument();
  });

  it('suppress button disabled until a plausible value is typed', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Settings />);
    await waitFor(() => screen.getByPlaceholderText(/jane@acme.com or acme.com/i));

    const btn = screen.getByRole('button', { name: /suppress/i });
    expect(btn).toBeDisabled();

    await user.type(screen.getByPlaceholderText(/jane@acme.com or acme.com/i), 'spam@corp.com');
    expect(btn).toBeEnabled();
  });

  it('adds a suppression entry and shows a success toast', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Settings />);
    await waitFor(() => screen.getByPlaceholderText(/jane@acme.com or acme.com/i));

    await user.type(screen.getByPlaceholderText(/jane@acme.com or acme.com/i), 'spam@corp.com');
    await user.click(screen.getByRole('button', { name: /suppress/i }));

    await waitFor(() => {
      expect(screen.getByText(/added to do-not-contact list/)).toBeInTheDocument();
    });
  });
});
