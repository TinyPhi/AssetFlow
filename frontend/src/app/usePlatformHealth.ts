// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// Polls the public health endpoint, which returns only {status}. Provider details live behind the
// platform-admin endpoint /api/health/providers and are never fetched by the public shell.
import { useQuery, type UseQueryResult } from "@tanstack/react-query";

export const HEALTH_POLL_MS = 15000;
export const HEALTH_TIMEOUT_MS = 10000;

export interface PublicHealth {
  status: string;
}

export class HealthCheckError extends Error {
  readonly httpStatus: number;

  constructor(httpStatus: number) {
    super(`Health check failed with HTTP ${httpStatus.toString()}`);
    this.name = "HealthCheckError";
    this.httpStatus = httpStatus;
  }
}

function isPublicHealth(value: unknown): value is PublicHealth {
  if (typeof value !== "object" || value === null || !("status" in value)) {
    return false;
  }
  return typeof value.status === "string";
}

export async function fetchPublicHealth(): Promise<PublicHealth> {
  // A probe that hangs must not hold the status on "checking" for ever: give up after 10 s.
  const controller = new AbortController();
  const timer = setTimeout(() => {
    controller.abort();
  }, HEALTH_TIMEOUT_MS);
  try {
    const res = await fetch("/api/health", {
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
    if (!res.ok) {
      throw new HealthCheckError(res.status);
    }
    const body: unknown = await res.json();
    if (!isPublicHealth(body)) {
      throw new HealthCheckError(res.status);
    }
    return { status: body.status };
  } finally {
    clearTimeout(timer);
  }
}

export function usePlatformHealth(): UseQueryResult<PublicHealth> {
  return useQuery<PublicHealth>({
    queryKey: ["publicHealth"],
    queryFn: fetchPublicHealth,
    refetchInterval: HEALTH_POLL_MS,
    retry: 1,
  });
}

/** True only when the latest probe succeeded and reported status "ok". */
export function isHealthy(result: Pick<UseQueryResult<PublicHealth>, "data" | "isError">): boolean {
  return !result.isError && result.data?.status === "ok";
}
