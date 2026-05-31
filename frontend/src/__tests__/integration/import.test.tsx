import { describe, it, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../utils';
import Import from '../../pages/Import';

const CSV_CONTENT = 'name,email,company\nJohn Doe,john@example.com,Tech Corp\nJane Smith,jane@example.com,Labs Inc';

describe('Import page', () => {
  it('renders the page header', () => {
    renderWithProviders(<Import />);
    expect(screen.getByText('Import')).toBeInTheDocument();
    expect(screen.getByText('Upload leads from CSV files')).toBeInTheDocument();
  });

  it('renders the drop zone', () => {
    renderWithProviders(<Import />);
    expect(screen.getByText('Drop CSV here')).toBeInTheDocument();
  });

  it('shows CSV format requirement text', () => {
    renderWithProviders(<Import />);
    expect(screen.getByText(/CSV format required/i)).toBeInTheDocument();
  });

  it('renders the file input for browsing', () => {
    const { container } = renderWithProviders(<Import />);
    expect(container.querySelector('input[type="file"]')).toBeInTheDocument();
  });

  it('file input accepts only CSV', () => {
    const { container } = renderWithProviders(<Import />);
    expect(container.querySelector('input[type="file"]')).toHaveAttribute('accept', '.csv');
  });

  it('shows import history section title', async () => {
    renderWithProviders(<Import />);
    await waitFor(() => {
      expect(screen.getByText(/import history/i)).toBeInTheDocument();
    });
  });

  it('shows import history after data loads', async () => {
    renderWithProviders(<Import />);
    await waitFor(() => {
      expect(screen.getByText('leads_2024_01_15.csv')).toBeInTheDocument();
    });
  });

  it('shows import history stats with check mark', async () => {
    renderWithProviders(<Import />);
    await waitFor(() => {
      expect(screen.getByText(/47✓/)).toBeInTheDocument();
    });
  });

  it('shows import result card after file upload', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Import />);

    const file = new File([CSV_CONTENT], 'test.csv', { type: 'text/csv' });
    const fileInput = document.querySelector('input[type="file"]') as HTMLElement;

    await user.upload(fileInput, file);

    // MSW handler returns { total: 50, successful: 47, ... }
    await waitFor(() => {
      expect(screen.getByText('Import Complete')).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('shows imported count in result card', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Import />);

    const file = new File([CSV_CONTENT], 'leads.csv', { type: 'text/csv' });
    const fileInput = document.querySelector('input[type="file"]') as HTMLElement;
    await user.upload(fileInput, file);

    await waitFor(() => {
      expect(screen.getByText('Import Complete')).toBeInTheDocument();
    });

    // "47" imported, "3" duplicates from mock
    expect(screen.getByText('47')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('shows CSV format guide', () => {
    renderWithProviders(<Import />);
    expect(screen.getByText(/CSV format guide/i)).toBeInTheDocument();
  });

  it('shows required field badges in the drop zone', () => {
    renderWithProviders(<Import />);
    expect(screen.getByText('name')).toBeInTheDocument();
    expect(screen.getByText('email')).toBeInTheDocument();
    expect(screen.getByText('company')).toBeInTheDocument();
    expect(screen.getByText('source (optional)')).toBeInTheDocument();
  });
});
