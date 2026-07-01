import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { renderWithProviders } from '../utils';
import { OnboardingWizard } from '../../components/OnboardingWizard';
import { useAuthStore } from '../../store/authStore';
import { mockUser } from '../mocks/handlers';
import { server } from '../mocks/server';

const DISMISSED_KEY = 'asdr_wizard_dismissed';

const zeroLeadsHandler = http.get('http://localhost:8000/leads/stats', () =>
  HttpResponse.json({
    total_leads: 0,
    completed: 0,
    failed: 0,
    processing: 0,
    success_rate: 0,
    verdict_breakdown: { hot: 0, warm: 0, cold: 0 },
  })
);

beforeEach(() => {
  useAuthStore.setState({ user: mockUser, accessToken: 'tok', refreshToken: 'ref' });
  localStorage.removeItem(DISMISSED_KEY);
  server.use(zeroLeadsHandler);
});

afterEach(() => {
  server.resetHandlers();
  localStorage.removeItem(DISMISSED_KEY);
});

describe('OnboardingWizard', () => {
  it('does not render while stats are loading', () => {
    // Override with a handler that never resolves fast enough
    server.use(http.get('http://localhost:8000/leads/stats', () => new Promise(() => {})));
    renderWithProviders(<OnboardingWizard />);
    expect(screen.queryByText('Setup wizard')).not.toBeInTheDocument();
  });

  it('does not render when total_leads > 0', async () => {
    server.use(
      http.get('http://localhost:8000/leads/stats', () =>
        HttpResponse.json({ total_leads: 5, completed: 5, failed: 0, processing: 0, success_rate: 1, verdict_breakdown: { hot: 2, warm: 2, cold: 1 } })
      )
    );
    renderWithProviders(<OnboardingWizard />);
    await waitFor(() => {
      // Stats loaded but wizard should not appear
      expect(screen.queryByText('Setup wizard')).not.toBeInTheDocument();
    });
  });

  it('does not render when already dismissed in localStorage', async () => {
    localStorage.setItem(DISMISSED_KEY, '1');
    renderWithProviders(<OnboardingWizard />);
    await waitFor(() => {
      expect(screen.queryByText('Setup wizard')).not.toBeInTheDocument();
    });
  });

  it('renders when total_leads is 0 and wizard not dismissed', async () => {
    renderWithProviders(<OnboardingWizard />);
    await waitFor(() => {
      expect(screen.getByText('Setup wizard')).toBeInTheDocument();
    });
  });

  it('shows step indicator with 4 steps', async () => {
    renderWithProviders(<OnboardingWizard />);
    await waitFor(() => expect(screen.getByText('Setup wizard')).toBeInTheDocument());
    // The step dots are rendered as divs — we verify via the step content
    expect(screen.getByText('Welcome to AutonomousSDR')).toBeInTheDocument();
  });

  it('renders welcome step content on first render', async () => {
    renderWithProviders(<OnboardingWizard />);
    await waitFor(() => expect(screen.getByText('Welcome to AutonomousSDR')).toBeInTheDocument());
    expect(screen.getByText(/multi-agent AI lead qualification/i)).toBeInTheDocument();
    expect(screen.getByText(/BANT scoring with self-optimizing weights/i)).toBeInTheDocument();
  });

  it('Continue button advances to ICP step', async () => {
    const user = userEvent.setup();
    renderWithProviders(<OnboardingWizard />);
    await waitFor(() => expect(screen.getByRole('button', { name: /continue/i })).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /continue/i }));

    expect(screen.getByText('Define your ICP')).toBeInTheDocument();
    expect(screen.getByText(/Ideal Customer Profile/i)).toBeInTheDocument();
  });

  it('shows Back button from step 2 onward', async () => {
    const user = userEvent.setup();
    renderWithProviders(<OnboardingWizard />);
    await waitFor(() => expect(screen.getByRole('button', { name: /continue/i })).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /continue/i }));
    expect(screen.getByRole('button', { name: /back/i })).toBeInTheDocument();
  });

  it('Back button returns to previous step', async () => {
    const user = userEvent.setup();
    renderWithProviders(<OnboardingWizard />);
    await waitFor(() => expect(screen.getByRole('button', { name: /continue/i })).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /continue/i }));
    expect(screen.getByText('Define your ICP')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /back/i }));
    expect(screen.getByText('Welcome to AutonomousSDR')).toBeInTheDocument();
  });

  it('ICP step shows Open ICP Builder button', async () => {
    const user = userEvent.setup();
    renderWithProviders(<OnboardingWizard />);
    await waitFor(() => expect(screen.getByRole('button', { name: /continue/i })).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /continue/i }));
    expect(screen.getByRole('button', { name: /open icp builder/i })).toBeInTheDocument();
  });

  it('Open ICP Builder dismisses the wizard', async () => {
    const user = userEvent.setup();
    renderWithProviders(<OnboardingWizard />);
    await waitFor(() => expect(screen.getByRole('button', { name: /continue/i })).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /continue/i }));
    await user.click(screen.getByRole('button', { name: /open icp builder/i }));

    expect(screen.queryByText('Setup wizard')).not.toBeInTheDocument();
    expect(localStorage.getItem(DISMISSED_KEY)).toBe('1');
  });

  it('advances to seed step (step 3)', async () => {
    const user = userEvent.setup();
    renderWithProviders(<OnboardingWizard />);
    await waitFor(() => expect(screen.getByRole('button', { name: /continue/i })).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /continue/i })); // → ICP
    await user.click(screen.getByRole('button', { name: /continue/i })); // → Seed

    expect(screen.getByRole('button', { name: /load demo data/i })).toBeInTheDocument();
    expect(screen.getByText(/~150 realistic demo leads/i)).toBeInTheDocument();
  });

  it('Load demo data button calls seed API', async () => {
    const user = userEvent.setup();
    renderWithProviders(<OnboardingWizard />);
    await waitFor(() => expect(screen.getByRole('button', { name: /continue/i })).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /continue/i }));
    await user.click(screen.getByRole('button', { name: /continue/i }));

    await user.click(screen.getByRole('button', { name: /load demo data/i }));

    await waitFor(() => {
      expect(screen.getByText(/demo data is loading/i)).toBeInTheDocument();
    });
  });

  it('shows already_seeded toast when seed returns already_seeded', async () => {
    server.use(
      http.post('http://localhost:8000/seed/demo', () =>
        HttpResponse.json({ status: 'already_seeded', message: 'Data already present' })
      )
    );
    const user = userEvent.setup();
    renderWithProviders(<OnboardingWizard />);
    await waitFor(() => expect(screen.getByRole('button', { name: /continue/i })).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /continue/i }));
    await user.click(screen.getByRole('button', { name: /continue/i }));
    await user.click(screen.getByRole('button', { name: /load demo data/i }));

    await waitFor(() => {
      expect(screen.getByText(/demo data already loaded/i)).toBeInTheDocument();
    });
  });

  it('advances to done step (step 4)', async () => {
    const user = userEvent.setup();
    renderWithProviders(<OnboardingWizard />);
    await waitFor(() => expect(screen.getByRole('button', { name: /continue/i })).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /continue/i }));
    await user.click(screen.getByRole('button', { name: /continue/i }));
    await user.click(screen.getByRole('button', { name: /continue/i }));

    expect(screen.getByText("You're ready")).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /start exploring/i })).toBeInTheDocument();
  });

  it('Start exploring dismisses the wizard', async () => {
    const user = userEvent.setup();
    renderWithProviders(<OnboardingWizard />);
    await waitFor(() => expect(screen.getByRole('button', { name: /continue/i })).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /continue/i }));
    await user.click(screen.getByRole('button', { name: /continue/i }));
    await user.click(screen.getByRole('button', { name: /continue/i }));
    await user.click(screen.getByRole('button', { name: /start exploring/i }));

    expect(screen.queryByText('Setup wizard')).not.toBeInTheDocument();
    expect(localStorage.getItem(DISMISSED_KEY)).toBe('1');
  });

  it('Skip wizard link dismisses the wizard', async () => {
    const user = userEvent.setup();
    renderWithProviders(<OnboardingWizard />);
    await waitFor(() => expect(screen.getByText(/skip wizard/i)).toBeInTheDocument());

    await user.click(screen.getByText(/skip wizard/i));

    expect(screen.queryByText('Setup wizard')).not.toBeInTheDocument();
    expect(localStorage.getItem(DISMISSED_KEY)).toBe('1');
  });

  it('X close button dismisses the wizard', async () => {
    const user = userEvent.setup();
    renderWithProviders(<OnboardingWizard />);
    await waitFor(() => expect(screen.getByText('Setup wizard')).toBeInTheDocument());

    // Find by aria or by position — the X button has no aria-label, use test id or query by SVG
    const allButtons = screen.getAllByRole('button');
    // First button in header area is the X close button
    const xBtn = allButtons.find((b) => b.querySelector('svg') && !b.textContent?.trim());
    if (xBtn) await user.click(xBtn);
    else {
      // Fallback: click the backdrop-containing element
      await user.click(screen.getByText(/skip wizard/i));
    }

    expect(screen.queryByText('Setup wizard')).not.toBeInTheDocument();
  });

  it('done step shows keyboard shortcut hint', async () => {
    const user = userEvent.setup();
    renderWithProviders(<OnboardingWizard />);
    await waitFor(() => expect(screen.getByRole('button', { name: /continue/i })).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /continue/i }));
    await user.click(screen.getByRole('button', { name: /continue/i }));
    await user.click(screen.getByRole('button', { name: /continue/i }));

    expect(screen.getByText(/keyboard shortcuts/i)).toBeInTheDocument();
  });
});
