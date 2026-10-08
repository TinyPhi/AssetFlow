// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { useRef } from "react";
import { t, type TranslationKey } from "@/lib/i18n";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { CONTROL_CLASS } from "./control-class";

export type DetailTab = "details" | "components" | "custody" | "history";

export const DETAIL_TABS: readonly { id: DetailTab; labelKey: TranslationKey }[] = [
  { id: "details", labelKey: "assets.detail.tab_details" },
  { id: "components", labelKey: "assets.detail.tab_components" },
  { id: "custody", labelKey: "assets.detail.tab_custody" },
  { id: "history", labelKey: "assets.detail.tab_history" },
];

const TABS_QUERY = "(min-width: 768px)";

interface DetailTabsProps {
  value: DetailTab;
  onChange: (tab: DetailTab) => void;
}

/** Tabs from 768 px up (arrow keys move between them); a select below, so nothing scrolls sideways. */
export const DetailTabs: React.FC<DetailTabsProps> = ({ value, onChange }) => {
  const wide = useMediaQuery(TABS_QUERY);
  const buttons = useRef<Record<string, HTMLButtonElement | null>>({});

  if (!wide) {
    return (
      <div>
        <label htmlFor="asset-tab-select" className="sr-only">
          {t("assets.detail.tabs_label")}
        </label>
        <select
          id="asset-tab-select"
          value={value}
          onChange={(event) => {
            const next = DETAIL_TABS.find((tab) => tab.id === event.target.value);
            if (next !== undefined) onChange(next.id);
          }}
          className={CONTROL_CLASS}
        >
          {DETAIL_TABS.map((tab) => (
            <option key={tab.id} value={tab.id}>
              {t(tab.labelKey)}
            </option>
          ))}
        </select>
      </div>
    );
  }

  const move = (from: number, step: number): void => {
    const next = DETAIL_TABS[(from + step + DETAIL_TABS.length) % DETAIL_TABS.length];
    if (next === undefined) return;
    onChange(next.id);
    buttons.current[next.id]?.focus();
  };

  return (
    <div
      role="tablist"
      aria-label={t("assets.detail.tabs_label")}
      className="flex gap-1 border-b border-border"
    >
      {DETAIL_TABS.map((tab, index) => (
        <button
          key={tab.id}
          ref={(node) => {
            buttons.current[tab.id] = node;
          }}
          type="button"
          role="tab"
          id={`asset-tab-${tab.id}`}
          aria-selected={value === tab.id}
          aria-controls="asset-tab-panel"
          tabIndex={value === tab.id ? 0 : -1}
          onClick={() => {
            onChange(tab.id);
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowRight") {
              event.preventDefault();
              move(index, 1);
            } else if (event.key === "ArrowLeft") {
              event.preventDefault();
              move(index, -1);
            }
          }}
          className={`min-h-11 border-b-2 px-4 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus ${
            value === tab.id
              ? "border-primary text-primary"
              : "border-transparent text-muted hover:text-foreground"
          }`}
        >
          {t(tab.labelKey)}
        </button>
      ))}
    </div>
  );
};
