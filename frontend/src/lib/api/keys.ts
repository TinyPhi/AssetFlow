// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// Query-key factory (§C4.9): every TanStack Query key is built here, so one feature can invalidate
// another's data without string typos. A feature adds its own factory next to `me`.

export const queryKeys = {
  me: () => ["me"] as const,
  health: () => ["health"] as const,
} as const;
