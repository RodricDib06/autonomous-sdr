import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { fireEvent } from '@testing-library/react';
import { useKeyboardShortcuts, SHORTCUTS } from '../../../hooks/useKeyboardShortcuts';

const makeOptions = (overrides = {}) => ({
  leads: [{ id: 'a' }, { id: 'b' }, { id: 'c' }],
  selectedIndex: 1,
  onSelectIndex: vi.fn(),
  onOpenLead: vi.fn(),
  onClose: vi.fn(),
  onFocusSearch: vi.fn(),
  onToggleCheatsheet: vi.fn(),
  ...overrides,
});

function press(key: string, options: KeyboardEventInit = {}) {
  fireEvent.keyDown(document, { key, ...options });
}

describe('useKeyboardShortcuts', () => {
  beforeEach(() => vi.clearAllMocks());

  it('j moves selection down', () => {
    const opts = makeOptions({ selectedIndex: 0 });
    renderHook(() => useKeyboardShortcuts(opts));
    press('j');
    expect(opts.onSelectIndex).toHaveBeenCalledWith(1);
  });

  it('ArrowDown moves selection down', () => {
    const opts = makeOptions({ selectedIndex: 0 });
    renderHook(() => useKeyboardShortcuts(opts));
    press('ArrowDown');
    expect(opts.onSelectIndex).toHaveBeenCalledWith(1);
  });

  it('j does not go past the last lead', () => {
    const opts = makeOptions({ selectedIndex: 2 }); // already at last (index 2 of 3)
    renderHook(() => useKeyboardShortcuts(opts));
    press('j');
    expect(opts.onSelectIndex).toHaveBeenCalledWith(2); // clamped to last
  });

  it('k moves selection up', () => {
    const opts = makeOptions({ selectedIndex: 2 });
    renderHook(() => useKeyboardShortcuts(opts));
    press('k');
    expect(opts.onSelectIndex).toHaveBeenCalledWith(1);
  });

  it('ArrowUp moves selection up', () => {
    const opts = makeOptions({ selectedIndex: 2 });
    renderHook(() => useKeyboardShortcuts(opts));
    press('ArrowUp');
    expect(opts.onSelectIndex).toHaveBeenCalledWith(1);
  });

  it('k does not go below 0', () => {
    const opts = makeOptions({ selectedIndex: 0 });
    renderHook(() => useKeyboardShortcuts(opts));
    press('k');
    expect(opts.onSelectIndex).toHaveBeenCalledWith(0);
  });

  it('o opens the currently selected lead', () => {
    const opts = makeOptions({ selectedIndex: 1 });
    renderHook(() => useKeyboardShortcuts(opts));
    press('o');
    expect(opts.onOpenLead).toHaveBeenCalledWith('b');
  });

  it('Enter opens the currently selected lead', () => {
    const opts = makeOptions({ selectedIndex: 0 });
    renderHook(() => useKeyboardShortcuts(opts));
    press('Enter');
    expect(opts.onOpenLead).toHaveBeenCalledWith('a');
  });

  it('o does nothing when selectedIndex is out of range', () => {
    const opts = makeOptions({ selectedIndex: -1 });
    renderHook(() => useKeyboardShortcuts(opts));
    press('o');
    expect(opts.onOpenLead).not.toHaveBeenCalled();
  });

  it('Escape calls onClose', () => {
    const opts = makeOptions();
    renderHook(() => useKeyboardShortcuts(opts));
    press('Escape');
    expect(opts.onClose).toHaveBeenCalled();
  });

  it('/ calls onFocusSearch', () => {
    const opts = makeOptions();
    renderHook(() => useKeyboardShortcuts(opts));
    press('/');
    expect(opts.onFocusSearch).toHaveBeenCalled();
  });

  it('? calls onToggleCheatsheet', () => {
    const opts = makeOptions();
    renderHook(() => useKeyboardShortcuts(opts));
    press('?');
    expect(opts.onToggleCheatsheet).toHaveBeenCalled();
  });

  it('ignores events when enabled=false', () => {
    const opts = makeOptions({ enabled: false });
    renderHook(() => useKeyboardShortcuts(opts));
    press('j');
    press('Escape');
    expect(opts.onSelectIndex).not.toHaveBeenCalled();
    expect(opts.onClose).not.toHaveBeenCalled();
  });

  it('ignores events originating from an input element', () => {
    const opts = makeOptions();
    renderHook(() => useKeyboardShortcuts(opts));

    // Simulate activeElement being an input by overriding document.activeElement
    const input = document.createElement('input');
    document.body.appendChild(input);
    vi.spyOn(document, 'activeElement', 'get').mockReturnValue(input);

    fireEvent.keyDown(document, { key: 'j' });
    expect(opts.onSelectIndex).not.toHaveBeenCalled();

    vi.restoreAllMocks();
    document.body.removeChild(input);
  });

  it('ignores events with metaKey held', () => {
    const opts = makeOptions();
    renderHook(() => useKeyboardShortcuts(opts));
    press('j', { metaKey: true });
    expect(opts.onSelectIndex).not.toHaveBeenCalled();
  });

  it('ignores events with ctrlKey held', () => {
    const opts = makeOptions();
    renderHook(() => useKeyboardShortcuts(opts));
    press('/', { ctrlKey: true });
    expect(opts.onFocusSearch).not.toHaveBeenCalled();
  });

  it('removes event listener on unmount', () => {
    const spy = vi.spyOn(document, 'removeEventListener');
    const opts = makeOptions();
    const { unmount } = renderHook(() => useKeyboardShortcuts(opts));
    unmount();
    expect(spy).toHaveBeenCalledWith('keydown', expect.any(Function));
    spy.mockRestore();
  });
});

describe('SHORTCUTS constant', () => {
  it('has all expected shortcut entries', () => {
    expect(SHORTCUTS).toHaveLength(6);
    const labels = SHORTCUTS.map((s) => s.label);
    expect(labels).toContain('Next lead');
    expect(labels).toContain('Previous lead');
    expect(labels).toContain('Open lead detail');
    expect(labels).toContain('Close panel / clear');
    expect(labels).toContain('Focus search');
    expect(labels).toContain('Show shortcuts');
  });
});
