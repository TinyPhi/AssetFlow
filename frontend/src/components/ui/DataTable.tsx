// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { t } from "@/lib/i18n";

export interface Column<Row> {
  /** Stable key, also the React key of the column's cells. */
  id: string;
  /** Column heading (already translated by the caller). */
  header: string;
  cell: (row: Row) => React.ReactNode;
}

interface DataTableProps<Row> {
  columns: readonly Column<Row>[];
  rows: readonly Row[];
  rowKey: (row: Row) => string;
  /** Names the table for assistive technology. */
  caption?: string;
}

/**
 * A data table that becomes a stack of cards below the `md` breakpoint (§B10: no sideways scroll on
 * a phone). Both forms are in the page; CSS shows one. The first column is the card's title.
 */
export function DataTable<Row>({ columns, rows, rowKey, caption }: DataTableProps<Row>): React.ReactElement {
  const label = caption ?? t("ui.table.caption_fallback");
  const [first, ...rest] = columns;
  return (
    <>
      <table className="hidden w-full text-left text-sm md:table">
        <caption className="sr-only">{label}</caption>
        <thead className="border-b border-border text-muted">
          <tr>
            {columns.map((column) => (
              <th key={column.id} scope="col" className="px-3 py-2 font-medium">
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)} className="border-b border-border">
              {columns.map((column) => (
                <td key={column.id} className="px-3 py-3">
                  {column.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <ul aria-label={label} className="space-y-3 md:hidden">
        {rows.map((row) => (
          <li key={rowKey(row)} className="rounded-xl border border-border bg-surface p-4">
            {first !== undefined && <div className="mb-2 font-semibold">{first.cell(row)}</div>}
            <dl className="space-y-1 text-sm">
              {rest.map((column) => (
                <div key={column.id} className="flex justify-between gap-4">
                  <dt className="text-muted">{column.header}</dt>
                  <dd className="min-w-0 break-words text-right">{column.cell(row)}</dd>
                </div>
              ))}
            </dl>
          </li>
        ))}
      </ul>
    </>
  );
}
