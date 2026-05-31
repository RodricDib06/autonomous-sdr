import { describe, it, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../utils';
import Pipeline from '../../pages/Pipeline';

describe('Pipeline page', () => {
  it('renders the page header', () => {
    renderWithProviders(<Pipeline />);
    expect(screen.getByText('Pipeline')).toBeInTheDocument();
  });

  it('renders the subtitle', () => {
    renderWithProviders(<Pipeline />);
    expect(screen.getByText(/LangGraph multi-agent execution/i)).toBeInTheDocument();
  });

  it('renders the state machine card', () => {
    renderWithProviders(<Pipeline />);
    expect(screen.getByText(/LangGraph State Machine/i)).toBeInTheDocument();
  });

  it('renders all 10 pipeline node labels', () => {
    renderWithProviders(<Pipeline />);
    expect(screen.getByText('Orchestrate')).toBeInTheDocument();
    expect(screen.getByText('Enrich')).toBeInTheDocument();
    expect(screen.getByText('Research')).toBeInTheDocument();
    expect(screen.getByText('Intent')).toBeInTheDocument();
    expect(screen.getByText('Analyse')).toBeInTheDocument();
    expect(screen.getByText('Validate')).toBeInTheDocument();
    expect(screen.getByText('Booking')).toBeInTheDocument();
    expect(screen.getByText('Outreach')).toBeInTheDocument();
    expect(screen.getByText('CRM Sync')).toBeInTheDocument();
    expect(screen.getByText('Handoff')).toBeInTheDocument();
  });

  it('renders the Leads section', async () => {
    renderWithProviders(<Pipeline />);
    await waitFor(() => {
      expect(screen.getByText('Leads')).toBeInTheDocument();
    });
  });

  it('shows lead names from mock data', async () => {
    renderWithProviders(<Pipeline />);
    await waitFor(() => {
      expect(screen.getByText('John Doe')).toBeInTheDocument();
    });
  });

  it('shows run pipeline button for each lead', async () => {
    renderWithProviders(<Pipeline />);
    await waitFor(() => screen.getByText('John Doe'));
    expect(document.querySelectorAll('[title="Run pipeline live"]').length).toBeGreaterThan(0);
  });

  it('shows stage status count cards', () => {
    renderWithProviders(<Pipeline />);
    expect(screen.getByText('Pending')).toBeInTheDocument();
    expect(screen.getByText('Processing')).toBeInTheDocument();
    expect(screen.getByText('Complete')).toBeInTheDocument();
    expect(screen.getByText('Failed')).toBeInTheDocument();
  });

  it('shows "Click any lead" prompt when no lead is selected', async () => {
    renderWithProviders(<Pipeline />);
    await waitFor(() => {
      expect(screen.getByText(/Click any lead to view its trace/i)).toBeInTheDocument();
    });
  });

  it('shows ReAct research agent callout', () => {
    renderWithProviders(<Pipeline />);
    expect(screen.getByText(/ReAct Research Agent/i)).toBeInTheDocument();
  });

  it('clicking a lead shows the Execution Trace header', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Pipeline />);
    await waitFor(() => screen.getByText('John Doe'));

    const leadRow = screen.getAllByText('John Doe')[0].closest('[class*="cursor-pointer"]') as HTMLElement;
    await user.click(leadRow);

    await waitFor(() => {
      expect(screen.getByText('Execution Trace')).toBeInTheDocument();
    });
  });

  it('clicking a lead shows agent-by-agent breakdown description', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Pipeline />);
    await waitFor(() => screen.getByText('John Doe'));

    const leadRow = screen.getAllByText('John Doe')[0].closest('[class*="cursor-pointer"]') as HTMLElement;
    await user.click(leadRow);

    await waitFor(() => {
      expect(screen.getByText(/Agent-by-agent breakdown/i)).toBeInTheDocument();
    });
  });

  it('trace panel shows data from mock after clicking lead', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Pipeline />);
    await waitFor(() => screen.getByText('John Doe'));

    const leadRow = screen.getAllByText('John Doe')[0].closest('[class*="cursor-pointer"]') as HTMLElement;
    await user.click(leadRow);

    // TracePanel loads /leads/:id/pipeline-trace which returns lead_name "John Doe"
    await waitFor(() => {
      // GraphDiagram renders with the trace data
      expect(screen.getByText('Execution Trace')).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('clicking Run Live button shows Live Pipeline Stream header', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Pipeline />);
    await waitFor(() => screen.getByText('John Doe'));

    const runBtn = document.querySelectorAll('[title="Run pipeline live"]')[0] as HTMLElement;
    await user.click(runBtn);

    await waitFor(() => {
      expect(screen.getByText('Live Pipeline Stream')).toBeInTheDocument();
    });
  });

  it('live stream panel shows connecting status', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Pipeline />);
    await waitFor(() => screen.getByText('John Doe'));

    const runBtn = document.querySelectorAll('[title="Run pipeline live"]')[0] as HTMLElement;
    await user.click(runBtn);

    await waitFor(() => {
      expect(screen.getByText(/Connecting/i)).toBeInTheDocument();
    });
  });

  it('search filter hides non-matching leads', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Pipeline />);
    await waitFor(() => screen.getByText('John Doe'));

    const searchInput = screen.getByPlaceholderText('Search...');
    await user.type(searchInput, 'Jane');

    await waitFor(() => {
      expect(screen.queryByText('John Doe')).not.toBeInTheDocument();
      expect(screen.getByText('Jane Smith')).toBeInTheDocument();
    });
  });

  it('shows live execution graph in stream panel', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Pipeline />);
    await waitFor(() => screen.getByText('John Doe'));

    const runBtn = document.querySelectorAll('[title="Run pipeline live"]')[0] as HTMLElement;
    await user.click(runBtn);

    await waitFor(() => {
      expect(screen.getByText('Live Execution')).toBeInTheDocument();
    });
  });
});
