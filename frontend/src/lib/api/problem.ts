// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// RFC 9457 problem details as the API sends them (§C1.5.1), turned into one typed error.

export interface FieldError {
  field: string;
  message: string;
}

export class ProblemError extends Error {
  readonly code: string;
  readonly status: number;
  readonly detail: string;
  readonly errors: readonly FieldError[];
  readonly requestId: string | null;

  constructor(init: {
    code: string;
    status: number;
    detail: string;
    errors?: readonly FieldError[];
    requestId?: string | null;
  }) {
    super(init.detail);
    this.name = "ProblemError";
    this.code = init.code;
    this.status = init.status;
    this.detail = init.detail;
    this.errors = init.errors ?? [];
    this.requestId = init.requestId ?? null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function parseFieldErrors(value: unknown): FieldError[] {
  if (!Array.isArray(value)) return [];
  const result: FieldError[] = [];
  for (const item of value as unknown[]) {
    if (!isRecord(item)) continue;
    const field = asString(item["field"]);
    const message = asString(item["message"]);
    if (field !== null && message !== null) result.push({ field, message });
  }
  return result;
}

/** Build a `ProblemError` from a failed response's status and (already parsed) body. */
export function problemFrom(status: number, body: unknown): ProblemError {
  if (!isRecord(body)) {
    return new ProblemError({ code: "unknown", status, detail: "" });
  }
  return new ProblemError({
    code: asString(body["code"]) ?? "unknown",
    status,
    detail: asString(body["detail"]) ?? "",
    errors: parseFieldErrors(body["errors"]),
    requestId: asString(body["request_id"]),
  });
}

export function isProblemError(value: unknown): value is ProblemError {
  return value instanceof ProblemError;
}
