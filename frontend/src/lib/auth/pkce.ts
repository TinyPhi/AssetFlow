// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// Authorization code + PKCE (RFC 7636, S256) for the public OIDC client (§B11.2, AF-025). Only the
// short-lived redirect transaction (verifier, state, nonce) is kept in sessionStorage for the round trip
// to the IdP and removed on return; the access token is never written to browser storage (ADR-0011).

const TXN_KEY = "af.oidc.txn";
const RANDOM_BYTES = 32;

export interface LoginTransaction {
  codeVerifier: string;
  state: string;
  nonce: string;
}

export interface LoginRedirectParams {
  codeChallenge: string;
  codeChallengeMethod: "S256";
  state: string;
  nonce: string;
}

export class LoginTransactionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "LoginTransactionError";
  }
}

function base64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomToken(): string {
  return base64Url(crypto.getRandomValues(new Uint8Array(RANDOM_BYTES)));
}

/** The S256 code challenge for a verifier: BASE64URL(SHA-256(ASCII(verifier))). */
export async function codeChallengeS256(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64Url(new Uint8Array(digest));
}

function isTransaction(value: unknown): value is LoginTransaction {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return typeof v.codeVerifier === "string" && typeof v.state === "string" && typeof v.nonce === "string";
}

/** Start a login: create verifier, state and nonce, keep them for the return, and give the redirect values. */
export async function beginLoginTransaction(): Promise<LoginRedirectParams> {
  const txn: LoginTransaction = { codeVerifier: randomToken(), state: randomToken(), nonce: randomToken() };
  const codeChallenge = await codeChallengeS256(txn.codeVerifier);
  sessionStorage.setItem(TXN_KEY, JSON.stringify(txn));
  return { codeChallenge, codeChallengeMethod: "S256", state: txn.state, nonce: txn.nonce };
}

/**
 * Finish a login on the callback: check the returned `state` against the stored one, remove the
 * transaction (single use, whatever the outcome) and return it for the session exchange.
 */
export function completeLoginTransaction(returnedState: string | null): LoginTransaction {
  const raw = sessionStorage.getItem(TXN_KEY);
  sessionStorage.removeItem(TXN_KEY);
  if (raw === null) throw new LoginTransactionError("No sign-in is in progress.");
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new LoginTransactionError("The sign-in state is damaged.");
  }
  if (!isTransaction(parsed)) throw new LoginTransactionError("The sign-in state is damaged.");
  if (returnedState === null || returnedState !== parsed.state) {
    throw new LoginTransactionError("The sign-in response did not match the request.");
  }
  return parsed;
}
