// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { Columns3 } from "lucide-react";
import type React from "react";
import { useState } from "react";
import { t } from "@/lib/i18n";
import { COLUMNS, type ColumnId } from "../lib/asset-columns";
import { BUTTON_CLASS } from "./control-class";

interface ColumnChooserProps {
  columns: readonly ColumnId[];
  onChange: (next: readonly ColumnId[]) => void;
}

/** Choose the table's columns (the name column is always shown so a row stays identifiable). */
export const ColumnChooser: React.FC<ColumnChooserProps> = ({ columns, onChange }) => {
  const [open, setOpen] = useState(false);
  return (
    <div className="contents">
      <button
        type="button"
        aria-expanded={open}
        aria-controls="column-chooser-panel"
        onClick={() => {
          setOpen(!open);
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
        className={BUTTON_CLASS}
      >
        <Columns3 aria-hidden="true" className="h-4 w-4" />
        {t("assets.columns.choose")}
      </button>
      {open && (
        <fieldset
          id="column-chooser-panel"
          className="order-last w-full rounded-xl border border-border bg-surface p-4"
        >
          <legend className="px-1 text-xs font-medium text-muted">{t("assets.columns.choose")}</legend>
          <div className="flex flex-wrap gap-x-4">
            {COLUMNS.map((column) => (
              <label key={column.id} className="flex min-h-11 items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={columns.includes(column.id)}
                  disabled={column.id === "name"}
                  onChange={(event) => {
                    onChange(
                      event.target.checked
                        ? [...columns, column.id]
                        : columns.filter((id) => id !== column.id),
                    );
                  }}
                  className="h-5 w-5 accent-primary"
                />
                {t(column.labelKey)}
              </label>
            ))}
          </div>
        </fieldset>
      )}
    </div>
  );
};
