/**
 * Turns attempted full-page navigations into test failures.
 *
 * jsdom does not navigate on `location.href = ...`; it logs
 * "Not implemented: navigation to another Document" and carries on. The setup
 * file used to filter that message out as noise — so when the 401 interceptor
 * started hard-reloading the page on a failed sign-in, every run printed the
 * warning and every test still passed. In a real browser that reload wiped the
 * error toast and reset the form, which is what "the login button does
 * nothing" turned out to be.
 *
 * Navigations are recorded rather than asserted globally: several of them are
 * kicked off from React Query onSuccess callbacks that resolve after their own
 * test's afterEach, so a suite-wide check blames whichever test happens to run
 * next. Tests assert on `getNavigationAttempts()` directly instead, which is
 * precise about who navigated and when.
 */

const attempts: string[] = [];

export function getNavigationAttempts(): string[] {
  return [...attempts];
}

export function resetNavigationGuard(): void {
  attempts.length = 0;
}

export function installNavigationGuard(): void {
  const real = window.location;

  // A plain delegating object rather than a Proxy: `assign`/`replace` are
  // non-configurable own properties on the real Location, and a Proxy get trap
  // is required to return their actual values, so it cannot record them.
  const stand_in = {
    assign: (url: string) => { attempts.push(String(url)); },
    replace: (url: string) => { attempts.push(String(url)); },
    reload: () => { attempts.push('reload()'); },
    toString: () => real.href,
  } as unknown as Location;

  // Forward every readable part of the URL to the real location so the router
  // (and anything reading pathname/search) still sees history.pushState moves.
  for (const key of [
    'href', 'origin', 'protocol', 'host', 'hostname',
    'port', 'pathname', 'search', 'hash', 'ancestorOrigins',
  ] as const) {
    Object.defineProperty(stand_in, key, {
      configurable: true,
      enumerable: true,
      get: () => real[key as keyof Location],
      // Assigning href is the navigation we are hunting for.
      set: key === 'href' ? (value: string) => { attempts.push(String(value)); } : undefined,
    });
  }

  Object.defineProperty(window, 'location', {
    configurable: true,
    get: () => stand_in,
    set: (value: string) => { attempts.push(String(value)); },
  });
}
