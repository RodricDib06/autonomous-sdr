/**
 * useGlobalEvents — subscribes to the backend SSE global event stream.
 *
 * Handles:
 *  - Automatic reconnect with exponential back-off (max 30 s)
 *  - Auth token injection via query param (EventSource can't set headers)
 *  - Clean teardown on unmount
 *  - Typed event callbacks per event type
 */

import { useEffect, useRef } from "react";
import { SSE_BASE } from "../lib/api";
import type { GlobalEvent } from "../types";

interface UseGlobalEventsOptions {
  onLeadComplete?: (event: GlobalEvent) => void;
  onOptimization?: (event: GlobalEvent) => void;
  enabled?: boolean;
}

const INITIAL_DELAY_MS = 1_000;
const MAX_DELAY_MS = 30_000;

export function useGlobalEvents({
  onLeadComplete,
  onOptimization,
  enabled = true,
}: UseGlobalEventsOptions) {
  const esRef = useRef<EventSource | null>(null);
  const retryDelayRef = useRef(INITIAL_DELAY_MS);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!enabled) return;

    function connect() {
      if (!mountedRef.current) return;

      const token = localStorage.getItem("access_token");
      const url = token
        ? `${SSE_BASE}/events/stream?token=${encodeURIComponent(token)}`
        : `${SSE_BASE}/events/stream`;

      const es = new EventSource(url);
      esRef.current = es;

      es.addEventListener("connected", () => {
        retryDelayRef.current = INITIAL_DELAY_MS; // reset back-off on successful connect
      });

      es.addEventListener("lead_complete", (e: MessageEvent) => {
        try {
          const data: GlobalEvent = JSON.parse(e.data);
          onLeadComplete?.(data);
        } catch {
          // malformed payload — ignore
        }
      });

      es.addEventListener("optimization", (e: MessageEvent) => {
        try {
          const data: GlobalEvent = JSON.parse(e.data);
          onOptimization?.(data);
        } catch {
          // malformed payload — ignore
        }
      });

      es.onerror = () => {
        es.close();
        esRef.current = null;
        if (!mountedRef.current) return;

        // Exponential back-off reconnect
        retryTimerRef.current = setTimeout(() => {
          retryDelayRef.current = Math.min(retryDelayRef.current * 2, MAX_DELAY_MS);
          connect();
        }, retryDelayRef.current);
      };
    }

    connect();

    return () => {
      mountedRef.current = false;
      if (retryTimerRef.current) clearTimeout(retryTimerRef.current);
      esRef.current?.close();
      esRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);
}
