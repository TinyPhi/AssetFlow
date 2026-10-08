// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type { LoginTransaction } from "@/lib/auth";
import type { PublicConfig, SessionResponse } from "./types";

// Cookie-bound endpoints (refresh, logout) require this marker besides an allowed Origin, which the
// browser adds itself (§B11.2): a cross-site form post cannot set a custom header.
const COOKIE_REQUEST_HEADERS = { "X-Requested-With": "AssetFlow" } as const;

export async function fetchPublicConfig(): Promise<PublicConfig> {
  const res = await fetch("/api/config/public");
  if (!res.ok) throw new Error("Failed to load public config");
  return res.json() as Promise<PublicConfig>;
}

export async function exchangeSession(
  code: string,
  redirectUri: string,
  txn: LoginTransaction,
): Promise<SessionResponse> {
  const res = await fetch("/api/auth/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      code,
      redirect_uri: redirectUri,
      code_verifier: txn.codeVerifier,
      state: txn.state,
      nonce: txn.nonce,
    }),
  });
  if (!res.ok) throw new Error("Failed to exchange session");
  return res.json() as Promise<SessionResponse>;
}

export async function refreshSessionToken(): Promise<SessionResponse> {
  const res = await fetch("/api/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...COOKIE_REQUEST_HEADERS },
  });
  if (!res.ok) throw new Error("Failed to refresh session");
  return res.json() as Promise<SessionResponse>;
}

export async function logoutSession(): Promise<void> {
  await fetch("/api/auth/logout", {
    method: "POST",
    headers: { ...COOKIE_REQUEST_HEADERS },
  });
}
