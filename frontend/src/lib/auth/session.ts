// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// The in-memory session (§C4.9, ADR-0011): the access token lives only in this module's memory, never
// in localStorage or sessionStorage, so a script injected into the page cannot read it from storage.
// Sign-in, silent refresh and logout are wired in by P7-02b through the hooks below.

/** A new access token, optionally with its lifetime in seconds (`expires_in` from the BFF). */
export interface IssuedToken {
  token: string;
  expiresIn?: number;
}

export type RefreshHandler = () => Promise<string | IssuedToken | null>;

// Refresh this long before the token expires, so a request never goes out with an expired token.
const REFRESH_LEAD_MS = 30_000;

let accessToken: string | null = null;
let expiresAt: number | null = null;
let expiryTimer: ReturnType<typeof setTimeout> | null = null;
let refreshHandler: RefreshHandler | null = null;
let inFlight: Promise<string | null> | null = null;
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

export function getAccessToken(): string | null {
  return accessToken;
}

function clearExpiryTimer(): void {
  if (expiryTimer !== null) clearTimeout(expiryTimer);
  expiryTimer = null;
}

/**
 * Store the access token. With `expiresInSeconds`, the session counts as gone once the token expires,
 * and a silent refresh is started shortly before that; without it the token never expires locally.
 */
export function setAccessToken(token: string | null, expiresInSeconds?: number): void {
  clearExpiryTimer();
  accessToken = token;
  expiresAt = token !== null && expiresInSeconds !== undefined ? Date.now() + expiresInSeconds * 1000 : null;
  if (expiresAt !== null) {
    const refreshIn = Math.max(0, expiresAt - Date.now() - REFRESH_LEAD_MS);
    expiryTimer = setTimeout(() => {
      expiryTimer = null;
      void refreshSession();
    }, refreshIn);
  }
  notify();
}

export function clearSession(): void {
  clearExpiryTimer();
  accessToken = null;
  expiresAt = null;
  inFlight = null;
  notify();
}

/** A token is held and, when its lifetime is known, has not expired yet. */
export function hasSession(): boolean {
  return accessToken !== null && (expiresAt === null || Date.now() < expiresAt);
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
    .then((issued) => {
      if (issued === null || typeof issued === "string") {
        setAccessToken(issued);
        return issued;
      }
      setAccessToken(issued.token, issued.expiresIn);
      return issued.token;
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
