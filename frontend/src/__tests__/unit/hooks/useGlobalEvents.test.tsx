import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useGlobalEvents } from '../../../hooks/useGlobalEvents';

class MockEventSource {
  static lastInstance: MockEventSource;
  static instances: MockEventSource[] = [];

  url: string;
  listeners: Record<string, ((e: MessageEvent) => void)[]> = {};
  onerror: (() => void) | null = null;
  close = vi.fn();

  constructor(url: string) {
    this.url = url;
    MockEventSource.lastInstance = this;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, cb: (e: MessageEvent) => void) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(cb);
  }

  emit(type: string, data: unknown) {
    (this.listeners[type] ?? []).forEach((cb) =>
      cb({ data: JSON.stringify(data) } as MessageEvent)
    );
  }

  emitRaw(type: string, raw: string) {
    (this.listeners[type] ?? []).forEach((cb) =>
      cb({ data: raw } as MessageEvent)
    );
  }
}

beforeEach(() => {
  MockEventSource.instances = [];
  vi.stubGlobal('EventSource', MockEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  localStorage.removeItem('access_token');
});

describe('useGlobalEvents', () => {
  it('creates an EventSource connection on mount', () => {
    renderHook(() => useGlobalEvents({}));
    expect(MockEventSource.instances).toHaveLength(1);
    expect(MockEventSource.lastInstance.url).toContain('/events/stream');
  });

  it('does not create EventSource when enabled=false', () => {
    renderHook(() => useGlobalEvents({ enabled: false }));
    expect(MockEventSource.instances).toHaveLength(0);
  });

  it('appends token to URL when access_token is in localStorage', () => {
    localStorage.setItem('access_token', 'mytoken123');
    renderHook(() => useGlobalEvents({}));
    expect(MockEventSource.lastInstance.url).toContain('token=mytoken123');
  });

  it('omits token from URL when no access_token in localStorage', () => {
    renderHook(() => useGlobalEvents({}));
    expect(MockEventSource.lastInstance.url).not.toContain('token=');
  });

  it('calls onLeadComplete when lead_complete event fires', () => {
    const onLeadComplete = vi.fn();
    renderHook(() => useGlobalEvents({ onLeadComplete }));

    act(() => {
      MockEventSource.lastInstance.emit('lead_complete', { lead_name: 'Jane', company: 'Acme', verdict: 'Hot' });
    });

    expect(onLeadComplete).toHaveBeenCalledWith({ lead_name: 'Jane', company: 'Acme', verdict: 'Hot' });
  });

  it('calls onOptimization when optimization event fires', () => {
    const onOptimization = vi.fn();
    renderHook(() => useGlobalEvents({ onOptimization }));

    act(() => {
      MockEventSource.lastInstance.emit('optimization', { run_id: 'opt-1' });
    });

    expect(onOptimization).toHaveBeenCalledWith({ run_id: 'opt-1' });
  });

  it('does not throw when onLeadComplete is undefined', () => {
    renderHook(() => useGlobalEvents({}));
    expect(() => {
      act(() => MockEventSource.lastInstance.emit('lead_complete', { verdict: 'Hot' }));
    }).not.toThrow();
  });

  it('resets retry delay on successful "connected" event', () => {
    renderHook(() => useGlobalEvents({}));
    expect(() => {
      act(() => MockEventSource.lastInstance.emit('connected', {}));
    }).not.toThrow();
  });

  it('handles malformed JSON in lead_complete without throwing', () => {
    const onLeadComplete = vi.fn();
    renderHook(() => useGlobalEvents({ onLeadComplete }));

    expect(() => {
      act(() => MockEventSource.lastInstance.emitRaw('lead_complete', 'NOT JSON'));
    }).not.toThrow();

    expect(onLeadComplete).not.toHaveBeenCalled();
  });

  it('handles malformed JSON in optimization without throwing', () => {
    const onOptimization = vi.fn();
    renderHook(() => useGlobalEvents({ onOptimization }));

    expect(() => {
      act(() => MockEventSource.lastInstance.emitRaw('optimization', '{bad json'));
    }).not.toThrow();
  });

  it('closes EventSource on unmount', () => {
    const { unmount } = renderHook(() => useGlobalEvents({}));
    const es = MockEventSource.lastInstance;
    unmount();
    expect(es.close).toHaveBeenCalled();
  });

  it('triggers reconnect on EventSource error after delay', () => {
    vi.useFakeTimers();
    renderHook(() => useGlobalEvents({}));
    const firstEs = MockEventSource.lastInstance;

    act(() => {
      firstEs.onerror?.();
    });

    // Advance past the initial 1000ms reconnect delay
    act(() => { vi.advanceTimersByTime(1100); });

    expect(MockEventSource.instances).toHaveLength(2);
    vi.useRealTimers();
  });
});
