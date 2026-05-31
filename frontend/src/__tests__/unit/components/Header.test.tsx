import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../utils';
import { Header } from '../../../components/layout/Header';

describe('Header', () => {
  it('renders the title', () => {
    renderWithProviders(<Header title="My Page" />);
    expect(screen.getByText('My Page')).toBeInTheDocument();
  });

  it('renders subtitle when provided', () => {
    renderWithProviders(<Header title="My Page" subtitle="Some subtitle" />);
    expect(screen.getByText('Some subtitle')).toBeInTheDocument();
  });

  it('does not render subtitle when not provided', () => {
    renderWithProviders(<Header title="My Page" />);
    expect(screen.queryByText('Some subtitle')).not.toBeInTheDocument();
  });

  it('renders action buttons when provided', () => {
    renderWithProviders(<Header title="My Page" actions={<button>Export</button>} />);
    expect(screen.getByText('Export')).toBeInTheDocument();
  });

  it('clicking the refresh button does not throw', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Header title="Test" />);
    const refreshBtn = screen.getByTitle('Refresh data');
    await user.click(refreshBtn);
    expect(refreshBtn).toBeInTheDocument();
  });
});
