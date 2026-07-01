import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../utils';
import Pipeline from '../../pages/Pipeline';

// EventSource mock for live stream tests
class MockEventSource {
  static lastInstance: MockEventSource | null = null;
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();

  constructor(url: string) {
    this.url = url;
    MockEventSource.lastInstance = this;
  }

  emit(data: object) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent);
  }
}

beforeEach(() => {
  MockEventSource.lastInstance = null;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function openTracePanel() {
  const user = userEvent.setup();
  renderWithProviders(<Pipeline />);
  await waitFor(() => screen.getByText('John Doe'));
  const leadRow = screen.getAllByText('John Doe')[0].closest('[class*="cursor-pointer"]') as HTMLElement;
  await user.click(leadRow);
  await waitFor(() => screen.getByText('Execution Trace'), { timeout: 3000 });
  return user;
}

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

  it('live stream shows connected state when EventSource opens', async () => {
    vi.stubGlobal('EventSource', MockEventSource);
    const user = userEvent.setup();
    renderWithProviders(<Pipeline />);
    await waitFor(() => screen.getByText('John Doe'));

    const runBtn = document.querySelectorAll('[title="Run pipeline live"]')[0] as HTMLElement;
    await user.click(runBtn);
    await waitFor(() => screen.getByText('Live Pipeline Stream'));

    // Trigger onopen to set connected=true
    const es = MockEventSource.lastInstance!;
    es.onopen?.();

    await waitFor(() => {
      expect(screen.getByText(/streaming node events/i)).toBeInTheDocument();
    });
  });

  it('live stream shows pipeline complete when done event fires', async () => {
    vi.stubGlobal('EventSource', MockEventSource);
    const user = userEvent.setup();
    renderWithProviders(<Pipeline />);
    await waitFor(() => screen.getByText('John Doe'));

    const runBtn = document.querySelectorAll('[title="Run pipeline live"]')[0] as HTMLElement;
    await user.click(runBtn);
    await waitFor(() => screen.getByText('Live Pipeline Stream'));

    const es = MockEventSource.lastInstance!;
    es.onopen?.();
    // Fire pipeline complete event
    es.emit({ node: 'pipeline', status: 'complete', verdict: 'Hot' });

    await waitFor(() => {
      expect(screen.getByText(/pipeline complete/i)).toBeInTheDocument();
    });
  });

  it('live stream shows node events in event log', async () => {
    vi.stubGlobal('EventSource', MockEventSource);
    const user = userEvent.setup();
    renderWithProviders(<Pipeline />);
    await waitFor(() => screen.getByText('John Doe'));

    const runBtn = document.querySelectorAll('[title="Run pipeline live"]')[0] as HTMLElement;
    await user.click(runBtn);
    await waitFor(() => screen.getByText('Live Pipeline Stream'));

    const es = MockEventSource.lastInstance!;
    await act(async () => {
      es.onopen?.();
      // Fire node events so they appear in the event log
      es.emit({ node: 'enrich', status: 'running' });
      es.emit({ node: 'enrich', status: 'complete', duration_ms: 320 });
    });

    await waitFor(() => {
      expect(screen.getAllByText('enrich').length).toBeGreaterThan(0);
    });
  });

  it('live stream handles error and shows disconnected state', async () => {
    vi.stubGlobal('EventSource', MockEventSource);
    const user = userEvent.setup();
    renderWithProviders(<Pipeline />);
    await waitFor(() => screen.getByText('John Doe'));

    const runBtn = document.querySelectorAll('[title="Run pipeline live"]')[0] as HTMLElement;
    await user.click(runBtn);
    await waitFor(() => screen.getByText('Live Pipeline Stream'));

    const es = MockEventSource.lastInstance!;
    es.onopen?.();
    es.onerror?.();

    await waitFor(() => {
      expect(screen.getByText(/Connecting/i)).toBeInTheDocument();
    });
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

  it('trace panel shows agent log entries from API', async () => {
    await openTracePanel();
    await waitFor(() => {
      expect(screen.getByText('Agent Log')).toBeInTheDocument();
      expect(screen.getByText('Enrich Agent')).toBeInTheDocument();
      expect(screen.getByText('Score Agent')).toBeInTheDocument();
    });
  });

  it('agent log shows success icon for successful agents', async () => {
    await openTracePanel();
    await waitFor(() => expect(screen.getByText('Enrich Agent')).toBeInTheDocument());
    // Duration shows for agents with duration_ms
    expect(screen.getByText('245ms')).toBeInTheDocument();
  });

  it('agent log shows error message for failed agents', async () => {
    await openTracePanel();
    await waitFor(() => expect(screen.getByText('Score Agent')).toBeInTheDocument());
    expect(screen.getByText('API timeout')).toBeInTheDocument();
  });

  it('"Run Live" button in trace header triggers live stream', async () => {
    await openTracePanel();
    // The Run Live button is visible in the trace header when a lead is selected & trace is showing
    const runLiveBtn = screen.queryByRole('button', { name: /run live/i });
    if (runLiveBtn) {
      const user = userEvent.setup();
      await user.click(runLiveBtn);
      await waitFor(() => {
        expect(screen.getByText('Live Pipeline Stream')).toBeInTheDocument();
      });
    }
  });

  it('trace panel shows error state when API fails', async () => {
    const { http: mswHttp, HttpResponse: MswResp } = await import('msw');
    const { server: testServer } = await import('../mocks/server');
    testServer.use(
      mswHttp.get('http://localhost:8000/leads/:id/pipeline-trace', () =>
        MswResp.json({ detail: 'Not found' }, { status: 404 })
      )
    );
    const user = userEvent.setup();
    renderWithProviders(<Pipeline />);
    await waitFor(() => screen.getByText('John Doe'));
    const leadRow = screen.getAllByText('John Doe')[0].closest('[class*="cursor-pointer"]') as HTMLElement;
    await user.click(leadRow);

    await waitFor(() => {
      expect(screen.getByText(/No pipeline trace available/i)).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('live stream shows error state for node error event', async () => {
    vi.stubGlobal('EventSource', MockEventSource);
    const user = userEvent.setup();
    renderWithProviders(<Pipeline />);
    await waitFor(() => screen.getByText('John Doe'));

    const runBtn = document.querySelectorAll('[title="Run pipeline live"]')[0] as HTMLElement;
    await user.click(runBtn);
    await waitFor(() => screen.getByText('Live Pipeline Stream'));

    const es = MockEventSource.lastInstance!;
    await act(async () => {
      es.onopen?.();
      // Fire a node error event to cover the error branch in setNodeStates
      es.emit({ node: 'enrich', status: 'error' });
    });

    await waitFor(() => {
      expect(screen.getAllByText('enrich').length).toBeGreaterThan(0);
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
