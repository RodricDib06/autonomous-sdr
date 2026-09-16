import { describe, it, expect } from 'vitest';
import contracts from '../mocks/api-contracts.json';

/**
 * Guards the MSW handlers against drifting from the real API.
 *
 * These mocks are hand-written, and nothing used to tie them to what the
 * server actually returns. They drifted: the quality report mock published
 * `avg_quality_score` while the API sends `average_quality_score`, and its
 * distribution keys dropped the score ranges the real ones carry. Every test
 * passed; the Dashboard and Analytics panels rendered 0 in production. The
 * test count was never the problem — the fixture was lying.
 *
 * `api-contracts.json` is captured from a running server by
 * `scripts/capture_api_contracts.py` (key names only, no values). If this
 * test fails, either the mock is wrong or the API changed on purpose — in
 * which case re-run the capture script and commit the new contract.
 */

const BASE_URL = 'http://localhost:8000';

type Shape = string | Shape[] | { [k: string]: Shape };

function keysOf(shape: Shape): string[] {
  if (shape && typeof shape === 'object' && !Array.isArray(shape)) return Object.keys(shape).sort();
  return [];
}

/** Element shape for a list contract, or null when the capture saw an empty list. */
function elementOf(shape: Shape): Shape | null {
  if (Array.isArray(shape)) return shape.length ? shape[0] : null;
  return null;
}

describe('MSW handlers match the real API contract', () => {
  const entries = Object.entries(contracts as Record<string, Shape>);

  it('has contracts recorded to check against', () => {
    expect(entries.length).toBeGreaterThan(0);
  });

  for (const [endpoint, expectedShape] of entries) {
    const [method, path] = endpoint.split(' ');

    it(`${method} ${path} returns the documented keys`, async () => {
      const res = await fetch(`${BASE_URL}${path}`, { method });
      expect(res.status, `${endpoint} is not mocked`).toBe(200);
      const body = (await res.json()) as Shape;

      const expectedKeys = keysOf(expectedShape);
      if (expectedKeys.length) {
        // Every key the server sends must exist in the mock. Extra keys in the
        // mock are tolerated; missing ones are exactly the drift that bit us.
        const actualKeys = keysOf(body);
        const missing = expectedKeys.filter((k) => !actualKeys.includes(k));
        expect(missing, `${endpoint} mock is missing keys the API returns`).toEqual([]);
      }

      // Same check one level down for list payloads.
      const expectedEl = elementOf(expectedShape);
      const actualEl = elementOf(body);
      if (expectedEl && actualEl) {
        const missing = keysOf(expectedEl).filter((k) => !keysOf(actualEl).includes(k));
        expect(missing, `${endpoint} mock list items are missing keys`).toEqual([]);
      }

      // And inside the common {items: [...]} envelopes.
      if (expectedKeys.length && typeof expectedShape === 'object' && !Array.isArray(expectedShape)) {
        for (const key of expectedKeys) {
          const expNested = elementOf((expectedShape as Record<string, Shape>)[key]);
          const actNested = elementOf((body as Record<string, Shape>)?.[key]);
          if (expNested && actNested) {
            const missing = keysOf(expNested).filter((k) => !keysOf(actNested).includes(k));
            expect(missing, `${endpoint} -> ${key}[] is missing keys`).toEqual([]);
          }
        }
      }
    });
  }
});
