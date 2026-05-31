import { describe, it, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../utils';
import Leads from '../../pages/Leads';

async function setupDetailPanel() {
  const user = userEvent.setup();
  renderWithProviders(<Leads />);

  await waitFor(() => screen.getByText('John Doe'));

  // Click the lead row (tr has the onClick handler)
  const row = screen.getByText('John Doe').closest('tr')!;
  await user.click(row);

  // Wait for detail panel to appear (profile tab is default)
  await waitFor(() => screen.getByText('Senior VP Sales'), { timeout: 3000 });

  return user;
}

describe('Leads detail panel', () => {
  it('opens panel and shows lead name in header', async () => {
    await setupDetailPanel();
    expect(screen.getAllByText('John Doe').length).toBeGreaterThan(0);
    expect(screen.getByText('john@example.com · Tech Corp')).toBeInTheDocument();
  });

  it('shows enrichment data on default Profile tab', async () => {
    await setupDetailPanel();
    expect(screen.getByText('Senior VP Sales')).toBeInTheDocument();
    expect(screen.getByText('Technology')).toBeInTheDocument();
    expect(screen.getByText('executive')).toBeInTheDocument();
  });

  it('shows verdict badge in profile tab', async () => {
    await setupDetailPanel();
    // "Hot" appears in both the list row and the detail panel
    expect(screen.getAllByText('Hot').length).toBeGreaterThan(0);
  });

  it('shows tech stack in profile tab', async () => {
    await setupDetailPanel();
    expect(screen.getByText('Salesforce')).toBeInTheDocument();
  });

  it('switches to Intent tab and shows score', async () => {
    const user = await setupDetailPanel();
    await user.click(screen.getByText('Intent'));

    await waitFor(() => {
      expect(screen.getByText('Total Intent Score')).toBeInTheDocument();
      expect(screen.getByText('78%')).toBeInTheDocument();
    });
  });

  it('shows intent signals in Intent tab', async () => {
    const user = await setupDetailPanel();
    await user.click(screen.getByText('Intent'));

    await waitFor(() => {
      expect(screen.getByText(/recent funding/i)).toBeInTheDocument();
      expect(screen.getByText(/hiring signal/i)).toBeInTheDocument();
    });
  });

  it('shows triggered badge for active signals', async () => {
    const user = await setupDetailPanel();
    await user.click(screen.getByText('Intent'));

    await waitFor(() => {
      expect(screen.getAllByText('triggered').length).toBeGreaterThan(0);
    });
  });

  it('switches to Outreach tab and shows empty state', async () => {
    const user = await setupDetailPanel();
    await user.click(screen.getByText('Outreach'));

    await waitFor(() => {
      expect(screen.getByText(/no outreach scheduled yet/i)).toBeInTheDocument();
    });
  });

  it('switches to Activity tab and shows empty booking and conversation states', async () => {
    const user = await setupDetailPanel();
    await user.click(screen.getByText('Activity'));

    await waitFor(() => {
      expect(screen.getByText(/no bookings yet/i)).toBeInTheDocument();
      expect(screen.getByText(/no conversations yet/i)).toBeInTheDocument();
    });
  });

  it('shows Booking Requests and Conversations section headers', async () => {
    const user = await setupDetailPanel();
    await user.click(screen.getByText('Activity'));

    await waitFor(() => {
      expect(screen.getByText(/booking requests/i)).toBeInTheDocument();
      expect(screen.getAllByText(/conversations/i).length).toBeGreaterThan(0);
    });
  });

  it('switches to Trace tab and shows empty state', async () => {
    const user = await setupDetailPanel();
    await user.click(screen.getByText('Trace'));

    await waitFor(() => {
      expect(screen.getByText(/no pipeline trace available/i)).toBeInTheDocument();
    });
  });

  it('can switch between tabs multiple times', async () => {
    const user = await setupDetailPanel();

    await user.click(screen.getByText('Intent'));
    await waitFor(() => screen.getByText('Total Intent Score'));

    await user.click(screen.getByText('Profile'));
    await waitFor(() => screen.getByText('Senior VP Sales'));

    await user.click(screen.getByText('Outreach'));
    await waitFor(() => screen.getByText(/no outreach scheduled yet/i));
  });
});

describe('Leads bulk actions', () => {
  it('shows checkbox per row', async () => {
    renderWithProviders(<Leads />);
    await waitFor(() => screen.getByText('John Doe'));

    const checkboxes = document.querySelectorAll('input[type="checkbox"]');
    // 1 header checkbox + 3 row checkboxes = 4
    expect(checkboxes.length).toBeGreaterThanOrEqual(3);
  });

  it('shows bulk action bar when rows are selected', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Leads />);
    await waitFor(() => screen.getByText('John Doe'));

    const rowCheckboxes = document.querySelectorAll('tbody input[type="checkbox"]');
    await user.click(rowCheckboxes[0] as HTMLElement);

    await waitFor(() => {
      expect(screen.getByText(/1 selected/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /archive/i })).toBeInTheDocument();
    });
  });

  it('clears selection when Clear is clicked', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Leads />);
    await waitFor(() => screen.getByText('John Doe'));

    const rowCheckboxes = document.querySelectorAll('tbody input[type="checkbox"]');
    await user.click(rowCheckboxes[0] as HTMLElement);

    await waitFor(() => screen.getByText(/1 selected/i));
    await user.click(screen.getByRole('button', { name: /clear/i }));

    await waitFor(() => {
      expect(screen.queryByText(/selected/i)).not.toBeInTheDocument();
    });
  });

  it('selects all with header checkbox', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Leads />);
    await waitFor(() => screen.getByText('John Doe'));

    const headerCheckbox = document.querySelector('thead input[type="checkbox"]') as HTMLElement;
    await user.click(headerCheckbox);

    await waitFor(() => {
      expect(screen.getByText(/3 selected/i)).toBeInTheDocument();
    });
  });
});
