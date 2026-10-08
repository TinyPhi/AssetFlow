// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// The one way the web client talks to the API (§C4.9): components never call `fetch`. Base path
// /api/v1, Bearer token from the in-memory session, the success envelope unwrapped, and failures
// turned into `ProblemError`. One 401 triggers a single-flight refresh and one retry.
import { getAccessToken, refreshSession } from "@/lib/auth";
import { ProblemError, problemFrom } from "./problem";

export const API_BASE = "/api/v1";

export interface ApiInit {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  /** Sent as `Idempotency-Key`; create one per logical write with `newIdempotencyKey()`. */
  idempotencyKey?: string;
  signal?: AbortSignal;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function buildRequest(
  path: string,
  init: ApiInit,
  token: string | null,
): { url: string; options: RequestInit } {
  const headers = new Headers({ Accept: "application/json, application/problem+json" });
  // A null check on the session token, not a comparison of two secrets.
  // eslint-disable-next-line security/detect-possible-timing-attacks
  if (token !== null) headers.set("Authorization", `Bearer ${token}`);
  if (init.idempotencyKey !== undefined) headers.set("Idempotency-Key", init.idempotencyKey);
  const options: RequestInit = { method: init.method ?? "GET", headers };
  if (init.body !== undefined) {
    headers.set("Content-Type", "application/json");
    options.body = JSON.stringify(init.body);
  }
  if (init.signal !== undefined) options.signal = init.signal;
  return { url: `${API_BASE}${path}`, options };
}

async function readJson(res: Response): Promise<unknown> {
  if (res.status === 204) return undefined;
  try {
    return (await res.json()) as unknown;
  } catch {
    return undefined;
  }
}

async function send(path: string, init: ApiInit, token: string | null): Promise<Response> {
  const { url, options } = buildRequest(path, init, token);
  return fetch(url, options);
}

/** Call the API and return the unwrapped `data` of the success envelope. */
export async function apiFetch<T>(path: string, init: ApiInit = {}): Promise<T> {
  let res = await send(path, init, getAccessToken());
  if (res.status === 401) {
    const refreshed = await refreshSession();
    if (refreshed !== null) res = await send(path, init, refreshed);
  }
  const body = await readJson(res);
  if (!res.ok) throw problemFrom(res.status, body);
  if (body === undefined) return undefined as T;
  if (isRecord(body) && "data" in body) return body["data"] as T;
  throw new ProblemError({ code: "invalid_response", status: res.status, detail: "" });
}
