// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { t } from "@/lib/i18n";
import { renderApp } from "@/test/render";
import { applyTheme, initTheme, readStoredPreference, storePreference, THEME_STORAGE_KEY } from "./theme";

describe("theme preference", () => {
  it("defaults to system and ignores a stored value that is not a preference", () => {
    expect(readStoredPreference()).toBe("system");
    window.localStorage.setItem(THEME_STORAGE_KEY, "neon");
    expect(readStoredPreference()).toBe("system");
  });

  it("puts light or dark on the root element and nothing for system", () => {
    applyTheme("dark");
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    applyTheme("light");
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    applyTheme("system");
    expect(document.documentElement).not.toHaveAttribute("data-theme");
  });

  it("applies the stored choice at start-up", () => {
    storePreference("dark");
    expect(initTheme()).toBe("dark");
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  });

  it("still works when storage is blocked", () => {
    const failing = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const failingSet = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readStoredPreference()).toBe("system");
    expect(() => {
      storePreference("dark");
    }).not.toThrow();
    failing.mockRestore();
    failingSet.mockRestore();
  });
});

describe("theme toggle", () => {
  it("switches data-theme and remembers the choice", async () => {
    const user = userEvent.setup();
    renderApp("/");
    const group = await screen.findByRole("radiogroup", { name: t("theme.toggle.label") });
    expect(group).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: t("theme.toggle.system") })).toHaveAttribute("aria-checked", "true");

    await user.click(screen.getByRole("radio", { name: t("theme.toggle.dark") }));
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(screen.getByRole("radio", { name: t("theme.toggle.dark") })).toHaveAttribute("aria-checked", "true");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");

    await user.click(screen.getByRole("radio", { name: t("theme.toggle.light") }));
    expect(document.documentElement).toHaveAttribute("data-theme", "light");

    await user.click(screen.getByRole("radio", { name: t("theme.toggle.system") }));
    expect(document.documentElement).not.toHaveAttribute("data-theme");
  });
});
