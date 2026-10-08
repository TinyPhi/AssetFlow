// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { useCallback, useState } from "react";
import { applyTheme, readStoredPreference, storePreference, type ThemePreference } from "./theme";

export function useTheme(): { preference: ThemePreference; setPreference: (next: ThemePreference) => void } {
  const [preference, setCurrent] = useState<ThemePreference>(readStoredPreference);
  const setPreference = useCallback((next: ThemePreference) => {
    applyTheme(next);
    storePreference(next);
    setCurrent(next);
  }, []);
  return { preference, setPreference };
}
