// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

/** A fresh `Idempotency-Key` for one logical write; reuse the same key when retrying that write. */
export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}
