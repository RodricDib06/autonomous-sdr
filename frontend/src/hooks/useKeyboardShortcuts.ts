/**
 * useKeyboardShortcuts
 *
 * Wires document-level keyboard events for the Leads page:
 *   j / ArrowDown  — move selection down
 *   k / ArrowUp    — move selection up
 *   o / Enter      — open selected lead detail
 *   Escape         — close detail panel / cancel selection
 *   /              — focus search input
 *   ?              — toggle shortcuts cheatsheet
 *
 * Skips events originating from <input>, <textarea>, or [contenteditable]
 * so typing in search / forms is never intercepted.
 */

import { useEffect, useCallback } from "react";

interface ShortcutOptions {
  leads: { id: string }[];
  selectedIndex: number;
  onSelectIndex: (i: number) => void;
  onOpenLead: (id: string) => void;
  onClose: () => void;
  onFocusSearch: () => void;
  onToggleCheatsheet: () => void;
  enabled?: boolean;
}

function isEditable(el: Element | null): boolean {
  if (!el) return false;
  const tag = el.tagName.toLowerCase();
  return tag === "input" || tag === "textarea" || (el as HTMLElement).isContentEditable;
}

export function useKeyboardShortcuts({
  leads,
  selectedIndex,
  onSelectIndex,
  onOpenLead,
  onClose,
  onFocusSearch,
  onToggleCheatsheet,
  enabled = true,
}: ShortcutOptions) {
  const handleKey = useCallback(
    (e: KeyboardEvent) => {
      if (!enabled) return;
      if (isEditable(document.activeElement)) return;
      // Ignore modifier combos (Cmd+k etc.)
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      switch (e.key) {
        case "j":
        case "ArrowDown": {
          e.preventDefault();
          const next = Math.min(selectedIndex + 1, leads.length - 1);
          onSelectIndex(next);
          break;
        }
        case "k":
        case "ArrowUp": {
          e.preventDefault();
          const prev = Math.max(selectedIndex - 1, 0);
          onSelectIndex(prev);
          break;
        }
        case "o":
        case "Enter": {
          if (selectedIndex >= 0 && selectedIndex < leads.length) {
            e.preventDefault();
            onOpenLead(leads[selectedIndex].id);
          }
          break;
        }
        case "Escape":
          e.preventDefault();
          onClose();
          break;
        case "/":
          e.preventDefault();
          onFocusSearch();
          break;
        case "?":
          e.preventDefault();
          onToggleCheatsheet();
          break;
      }
    },
    [enabled, leads, selectedIndex, onSelectIndex, onOpenLead, onClose, onFocusSearch, onToggleCheatsheet]
  );

  useEffect(() => {
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [handleKey]);
}

export const SHORTCUTS = [
  { keys: ["j", "↓"], label: "Next lead" },
  { keys: ["k", "↑"], label: "Previous lead" },
  { keys: ["o", "↵"], label: "Open lead detail" },
  { keys: ["Esc"], label: "Close panel / clear" },
  { keys: ["/"], label: "Focus search" },
  { keys: ["?"], label: "Show shortcuts" },
] as const;
