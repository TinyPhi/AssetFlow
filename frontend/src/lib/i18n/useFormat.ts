// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// Hook to provide locale-aware formatting functions bound to current member context (§B10, §C4.9).
import { useMemo } from "react";
import { useMe } from "@/lib/permissions";
import { formatDate, formatDateTime, formatNumber, formatRelativeTime } from "./format";

export function useFormat() {
  const { data: me } = useMe();
  const locale = me?.locale ?? "en";
  const timezone = me?.organization.timezone ?? "UTC";

  return useMemo(
    () => ({
      locale,
      timezone,
      formatDate: (value: string | Date | number, options?: Intl.DateTimeFormatOptions) =>
        formatDate(value, locale, options),
      formatDateTime: (value: string | Date | number, options?: Intl.DateTimeFormatOptions) =>
        formatDateTime(value, timezone, locale, options),
      formatNumber: (value: number, options?: Intl.NumberFormatOptions) =>
        formatNumber(value, locale, options),
      formatRelativeTime: (value: string | Date | number, baseDate?: Date) =>
        formatRelativeTime(value, baseDate, locale),
    }),
    [locale, timezone],
  );
}
