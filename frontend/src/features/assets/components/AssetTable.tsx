// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import type React from "react";
import { t } from "@/lib/i18n";
import { columnDef, type ColumnId } from "../lib/asset-columns";
import { nextSort, type SortKey } from "../lib/asset-filter-params";
import type { AssetListItem } from "../types";
import { AssetCell } from "./AssetCells";

interface AssetTableProps {
  items: readonly AssetListItem[];
  columns: readonly ColumnId[];
  sort: string;
  /** False while a search is active: the API then ranks by relevance and ignores the sort. */
  sortApplies: boolean;
  onSort: (sort: string) => void;
}

function ariaSort(sort: string, key: SortKey, applies: boolean): "ascending" | "descending" | "none" {
  if (!applies) return "none";
  if (sort === key) return "ascending";
  if (sort === `-${key}`) return "descending";
  return "none";
}

/** The table form (1024 px and wider): sortable column headings, wrapping cells so it never scrolls sideways. */
export const AssetTable: React.FC<AssetTableProps> = ({ items, columns, sort, sortApplies, onSort }) => (
  <div className="overflow-hidden rounded-xl border border-border bg-surface">
    <table className="w-full table-auto text-left text-sm">
      <caption className="sr-only">{t("assets.list.table_caption")}</caption>
      <thead className="border-b border-border text-muted">
        <tr>
          {columns.map((id) => {
            const def = columnDef(id);
            const key = def.sort;
            return (
              <th
                key={id}
                scope="col"
                aria-sort={key === undefined ? undefined : ariaSort(sort, key, sortApplies)}
                className="px-3 py-1 font-medium"
              >
                {key === undefined ? (
                  <span className="inline-flex min-h-11 items-center">{t(def.labelKey)}</span>
                ) : (
                  <button
                    type="button"
                    onClick={() => {
                      onSort(nextSort(sort, key));
                    }}
                    className="inline-flex min-h-11 min-w-11 items-center gap-1 rounded font-medium hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
                  >
                    {t(def.labelKey)}
                    {!sortApplies || (sort !== key && sort !== `-${key}`) ? (
                      <ArrowUpDown aria-hidden="true" className="h-3.5 w-3.5" />
                    ) : sort === key ? (
                      <ArrowUp aria-hidden="true" className="h-3.5 w-3.5" />
                    ) : (
                      <ArrowDown aria-hidden="true" className="h-3.5 w-3.5" />
                    )}
                  </button>
                )}
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.id} className="border-b border-border last:border-b-0">
            {columns.map((id) => (
              <td key={id} className="min-w-0 break-words px-3 py-3 align-top">
                <AssetCell column={id} item={item} />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);
