// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// Theme preference: light, dark or "system" (follow the operating system). The choice is a per-viewer
// convenience, so it is kept in localStorage; storage can be blocked or throw (private windows), and
// the app must look right without it.
export type ThemePreference = "light" | "dark" | "system";

export const THEME_STORAGE_KEY = "assetflow.theme";
export const THEME_PREFERENCES: readonly ThemePreference[] = ["light", "dark", "system"];

function isPreference(value: unknown): value is ThemePreference {
  return value === "light" || value === "dark" || value === "system";
}

export function readStoredPreference(): ThemePreference {
  try {
    const raw = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isPreference(raw) ? raw : "system";
  } catch {
    return "system";
  }
}

export function storePreference(preference: ThemePreference): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // Storage is unavailable: the choice applies to this page view only.
  }
}

/** Put the preference on the root element: `data-theme="light|dark"`, or none for "system". */
export function applyTheme(preference: ThemePreference): void {
  const root = document.documentElement;
  if (preference === "system") {
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", preference);
  }
}

/** Apply the stored preference at start-up, before the first render. */
export function initTheme(): ThemePreference {
  const preference = readStoredPreference();
  applyTheme(preference);
  return preference;
}
