import { describe, it, expect, afterEach } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { renderWithProviders } from '../utils';
import Import from '../../pages/Import';
import { server } from '../mocks/server';

const CSV_CONTENT = 'name,email,company\nJohn Doe,john@example.com,Tech Corp\nJane Smith,jane@example.com,Labs Inc';

afterEach(() => {
  server.resetHandlers();
});

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

  it('shows success rate after import', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Import />);

    const file = new File([CSV_CONTENT], 'test.csv', { type: 'text/csv' });
    const fileInput = document.querySelector('input[type="file"]') as HTMLElement;
    await user.upload(fileInput, file);

    await waitFor(() => screen.getByText('Import Complete'));
    expect(screen.getByText('Success rate')).toBeInTheDocument();
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

  it('shows "0 imports" badge when history is empty', async () => {
    server.use(
      http.get('http://localhost:8000/leads/import-history', () =>
        HttpResponse.json({ imports: [], count: 0 })
      )
    );
    renderWithProviders(<Import />);
    await waitFor(() => {
      expect(screen.getByText('0 imports')).toBeInTheDocument();
      expect(screen.getByText(/No imports yet/i)).toBeInTheDocument();
    });
  });

  it('shows import errors in result card when errors exist', async () => {
    server.use(
      http.post('http://localhost:8000/leads/import-csv', () =>
        HttpResponse.json({
          total: 10, successful: 8, failed: 2, duplicates: 0,
          errors: ['Row 3: Invalid email format', 'Row 7: Missing company name'],
        })
      )
    );
    const user = userEvent.setup();
    renderWithProviders(<Import />);

    const file = new File([CSV_CONTENT], 'test.csv', { type: 'text/csv' });
    const fileInput = document.querySelector('input[type="file"]') as HTMLElement;
    await user.upload(fileInput, file);

    await waitFor(() => screen.getByText('Import Complete'));
    expect(screen.getByText(/Invalid email format/i)).toBeInTheDocument();
  });

  it('shows error toast when import fails', async () => {
    server.use(
      http.post('http://localhost:8000/leads/import-csv', () =>
        HttpResponse.json({ detail: 'Invalid CSV structure' }, { status: 400 })
      )
    );
    const user = userEvent.setup();
    renderWithProviders(<Import />);

    const file = new File([CSV_CONTENT], 'test.csv', { type: 'text/csv' });
    const fileInput = document.querySelector('input[type="file"]') as HTMLElement;
    await user.upload(fileInput, file);

    await waitFor(() => {
      expect(screen.getByText(/Invalid CSV structure/i)).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('changes dropzone appearance on drag over', async () => {
    const { container } = renderWithProviders(<Import />);
    const dropzone = container.querySelector('[class*="border-dashed"]') as HTMLElement;

    fireEvent.dragOver(dropzone, {
      dataTransfer: { files: [] },
    });

    // After dragOver, the text changes to "Drop it!"
    await waitFor(() => {
      expect(screen.getByText('Drop it!')).toBeInTheDocument();
    });
  });

  it('reverts dropzone appearance on drag leave', async () => {
    const { container } = renderWithProviders(<Import />);
    const dropzone = container.querySelector('[class*="border-dashed"]') as HTMLElement;

    fireEvent.dragOver(dropzone, { dataTransfer: { files: [] } });
    await waitFor(() => expect(screen.getByText('Drop it!')).toBeInTheDocument());

    fireEvent.dragLeave(dropzone);
    await waitFor(() => {
      expect(screen.getByText('Drop CSV here')).toBeInTheDocument();
    });
  });

  it('dropping a CSV file on the dropzone triggers upload', async () => {
    const { container } = renderWithProviders(<Import />);
    const dropzone = container.querySelector('[class*="border-dashed"]') as HTMLElement;

    const file = new File([CSV_CONTENT], 'dropped.csv', { type: 'text/csv' });
    fireEvent.drop(dropzone, {
      dataTransfer: { files: [file] },
    });

    await waitFor(() => {
      expect(screen.getByText('Import Complete')).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('dropping a non-CSV file shows error toast', async () => {
    const { container } = renderWithProviders(<Import />);
    const dropzone = container.querySelector('[class*="border-dashed"]') as HTMLElement;

    const file = new File(['hello'], 'data.txt', { type: 'text/plain' });
    fireEvent.drop(dropzone, {
      dataTransfer: { files: [file] },
    });

    await waitFor(() => {
      expect(screen.getByText(/Only CSV files are supported/i)).toBeInTheDocument();
    });
  });

  it('shows the format guide code example', () => {
    renderWithProviders(<Import />);
    expect(screen.getByText('name,email,company,source')).toBeInTheDocument();
    expect(screen.getByText(/John Smith,john@acme.com/i)).toBeInTheDocument();
  });

  it('shows checklist items in CSV format guide', () => {
    renderWithProviders(<Import />);
    expect(screen.getByText(/name, email, company are required/i)).toBeInTheDocument();
    expect(screen.getByText(/Duplicates are detected/i)).toBeInTheDocument();
  });

  it('shows import history item count badge with count', async () => {
    renderWithProviders(<Import />);
    await waitFor(() => {
      expect(screen.getByText('1 imports')).toBeInTheDocument();
    });
  });
});
