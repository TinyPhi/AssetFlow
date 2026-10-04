// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// Locale and timezone formatting utilities using standard Intl APIs (§B10, §C4.9).
// Inputs are always UTC ISO strings or Date instances.

export function parseDate(value: string | Date | number): Date {
  if (value instanceof Date) return value;
  return new Date(value);
}

export function formatDate(
  value: string | Date | number,
  locale = "en",
  options?: Intl.DateTimeFormatOptions,
): string {
  const date = parseDate(value);
  if (Number.isNaN(date.getTime())) return "";
  const formatter = new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    ...options,
  });
  return formatter.format(date);
}

export function formatDateTime(
  value: string | Date | number,
  timezone = "UTC",
  locale = "en",
  options?: Intl.DateTimeFormatOptions,
): string {
  const date = parseDate(value);
  if (Number.isNaN(date.getTime())) return "";
  const formatter = new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: timezone,
    ...options,
  });
  return formatter.format(date);
}

export function formatNumber(
  value: number,
  locale = "en",
  options?: Intl.NumberFormatOptions,
): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "";
  const formatter = new Intl.NumberFormat(locale, options);
  return formatter.format(value);
}

export function formatRelativeTime(
  value: string | Date | number,
  baseDate: Date = new Date(),
  locale = "en",
): string {
  const date = parseDate(value);
  if (Number.isNaN(date.getTime())) return "";

  const diffMs = date.getTime() - baseDate.getTime();
  const diffSec = Math.round(diffMs / 1000);
  const diffMin = Math.round(diffSec / 60);
  const diffHours = Math.round(diffMin / 60);
  const diffDays = Math.round(diffHours / 24);

  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });

  if (Math.abs(diffSec) < 60) {
    return formatter.format(diffSec, "second");
  }
  if (Math.abs(diffMin) < 60) {
    return formatter.format(diffMin, "minute");
  }
  if (Math.abs(diffHours) < 24) {
    return formatter.format(diffHours, "hour");
  }
  if (Math.abs(diffDays) < 30) {
    return formatter.format(diffDays, "day");
  }
  const diffMonths = Math.round(diffDays / 30);
  if (Math.abs(diffMonths) < 12) {
    return formatter.format(diffMonths, "month");
  }
  const diffYears = Math.round(diffDays / 365);
  return formatter.format(diffYears, "year");
}
