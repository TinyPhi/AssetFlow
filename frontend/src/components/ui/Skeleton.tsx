// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { t } from "@/lib/i18n";

/** The loading state of a list or page (§C4.9 four states): grey blocks, announced once. */
export const Skeleton: React.FC<{ rows?: number }> = ({ rows = 3 }) => (
  <div role="status" aria-busy="true" className="space-y-3">
    <span className="sr-only">{t("ui.loading")}</span>
    {Array.from({ length: rows }, (_, index) => (
      <div key={index} aria-hidden="true" className="h-10 w-full animate-pulse rounded-lg bg-border" />
    ))}
  </div>
);
