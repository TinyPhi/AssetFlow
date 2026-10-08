// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { Monitor, Moon, Sun, type LucideIcon } from "lucide-react";
import type React from "react";
import { t, type TranslationKey } from "@/lib/i18n";
import { useTheme, type ThemePreference } from "@/lib/theme";

const OPTIONS: readonly { value: ThemePreference; icon: LucideIcon; labelKey: TranslationKey }[] = [
  { value: "light", icon: Sun, labelKey: "theme.toggle.light" },
  { value: "dark", icon: Moon, labelKey: "theme.toggle.dark" },
  { value: "system", icon: Monitor, labelKey: "theme.toggle.system" },
];

/** Light, dark or follow the system; the choice is remembered in this browser. */
export const ThemeToggle: React.FC = () => {
  const { preference, setPreference } = useTheme();
  return (
    <div
      role="radiogroup"
      aria-label={t("theme.toggle.label")}
      className="flex rounded-lg border border-border"
    >
      {OPTIONS.map(({ value, icon: Icon, labelKey }) => {
        const selected = preference === value;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-label={t(labelKey)}
            title={t(labelKey)}
            onClick={() => {
              setPreference(value);
            }}
            className={`flex h-11 w-11 items-center justify-center first:rounded-l-lg last:rounded-r-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus ${
              selected ? "bg-primary text-primary-foreground" : "text-foreground hover:bg-border"
            }`}
          >
            <Icon aria-hidden="true" className="h-4 w-4" />
          </button>
        );
      })}
    </div>
  );
};
