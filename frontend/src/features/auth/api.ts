// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type { PublicConfig, SessionResponse } from "./types";

export async function fetchPublicConfig(): Promise<PublicConfig> {
  const res = await fetch("/api/config/public");
  if (!res.ok) throw new Error("Failed to load public config");
  return res.json() as Promise<PublicConfig>;
}

export async function exchangeSession(code: string, redirectUri: string, codeVerifier?: string): Promise<SessionResponse> {
  const res = await fetch("/api/auth/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, redirect_uri: redirectUri, code_verifier: codeVerifier }),
  });
  if (!res.ok) throw new Error("Failed to exchange session");
  return res.json() as Promise<SessionResponse>;
}

export async function refreshSessionToken(): Promise<SessionResponse> {
  const res = await fetch("/api/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) throw new Error("Failed to refresh session");
  return res.json() as Promise<SessionResponse>;
}

export async function logoutSession(): Promise<void> {
  await fetch("/api/auth/logout", {
    method: "POST",
  });
}
