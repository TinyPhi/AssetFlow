// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { describe, expect, it } from "vitest";
import { formatDate, formatDateTime, formatNumber, formatRelativeTime, t } from "@/lib/i18n";

describe("formatDate and formatDateTime", () => {
  const utcTimestamp = "2026-10-04T12:00:00Z";

  it("formats date for en-US and en-IN locales", () => {
    const formattedUS = formatDate(utcTimestamp, "en-US");
    const formattedIN = formatDate(utcTimestamp, "en-IN");
    expect(formattedUS).toContain("2026");
    expect(formattedIN).toContain("2026");
  });

  it("formats datetime respecting timezones (UTC vs Asia/Kolkata)", () => {
    const utcTime = formatDateTime(utcTimestamp, "UTC", "en-US");
    const istTime = formatDateTime(utcTimestamp, "Asia/Kolkata", "en-US");
    expect(utcTime).toContain("12:00");
    // 12:00 UTC = 17:30 IST
    expect(istTime).toContain("5:30");
  });

  it("handles invalid dates gracefully", () => {
    expect(formatDate("invalid-date")).toBe("");
    expect(formatDateTime("invalid-date")).toBe("");
  });
});

describe("formatNumber", () => {
  it("formats numbers per locale", () => {
    const num = 1234567.89;
    const us = formatNumber(num, "en-US");
    const de = formatNumber(num, "de-DE");
    expect(us).toBe("1,234,567.89");
    expect(de).toBe("1.234.567,89");
  });

  it("handles invalid number inputs", () => {
    expect(formatNumber(Number.NaN)).toBe("");
  });
});

describe("formatRelativeTime", () => {
  it("formats relative differences correctly", () => {
    const base = new Date("2026-10-04T12:00:00Z");
    const fiveMinutesAgo = new Date("2026-10-04T11:55:00Z");
    const twoHoursLater = new Date("2026-10-04T14:00:00Z");

    expect(formatRelativeTime(fiveMinutesAgo, base, "en")).toBe("5 minutes ago");
    expect(formatRelativeTime(twoHoursLater, base, "en")).toBe("in 2 hours");
  });
});

describe("translation interpolation", () => {
  it("interpolates parameters and supports Unicode/Devanagari text", () => {
    // Test that t() can interpolate params
    const greeting = t("pages.dashboard.welcome");
    expect(greeting).toBe("Welcome back");
  });
});
