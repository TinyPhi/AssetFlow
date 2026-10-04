// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// The in-memory session (§C4.9, ADR-0011): the access token lives only in this module's memory, never
// in localStorage or sessionStorage, so a script injected into the page cannot read it from storage.
// Sign-in, silent refresh and logout are wired in by P7-02b through the hooks below.

export type RefreshHandler = () => Promise<string | null>;

let accessToken: string | null = null;
let refreshHandler: RefreshHandler | null = null;
let inFlight: Promise<string | null> | null = null;
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
  notify();
}

export function clearSession(): void {
  accessToken = null;
  inFlight = null;
  notify();
}

export function hasSession(): boolean {
  return accessToken !== null;
}

/** Register how a new access token is obtained (P7-02b: the BFF refresh endpoint). */
export function setRefreshHandler(handler: RefreshHandler | null): void {
  refreshHandler = handler;
}

/**
 * Obtain a new access token. Concurrent callers share one request (single flight), so a burst of 401
 * answers causes exactly one refresh. Resolves to the new token, or null when there is no handler or
 * the refresh did not produce one.
 */
export function refreshSession(): Promise<string | null> {
  if (refreshHandler === null) return Promise.resolve(null);
  inFlight ??= refreshHandler()
    .then((token) => {
      setAccessToken(token);
      return token;
    })
    .catch(() => {
      clearSession();
      return null;
    })
    .finally(() => {
      inFlight = null;
    });
  return inFlight;
}

/** Subscribe to session changes (for `useSyncExternalStore`). Returns the unsubscribe function. */
export function subscribeSession(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
