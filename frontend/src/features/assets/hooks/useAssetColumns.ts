// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { useCallback, useState } from "react";
import { COLUMN_IDS, DEFAULT_COLUMNS, type ColumnId } from "../lib/asset-columns";

const STORAGE_KEY = "assetflow.assets.columns";

function read(): ColumnId[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === null) return [...DEFAULT_COLUMNS];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [...DEFAULT_COLUMNS];
    const chosen = COLUMN_IDS.filter((id) => (parsed as unknown[]).includes(id));
    return chosen.length > 0 ? chosen : [...DEFAULT_COLUMNS];
  } catch {
    return [...DEFAULT_COLUMNS];
  }
}

/**
 * The visible columns, in the fixed column order. Kept in `localStorage` as a per-viewer convenience
 * (the page works without it); applying a saved view replaces them through `setColumns`.
 */
export function useAssetColumns(): { columns: ColumnId[]; setColumns: (next: readonly string[]) => void } {
  const [columns, setState] = useState<ColumnId[]>(read);
  const setColumns = useCallback((next: readonly string[]) => {
    const chosen = COLUMN_IDS.filter((id) => next.includes(id));
    const value = chosen.length > 0 ? chosen : [...DEFAULT_COLUMNS];
    setState(value);
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
    } catch {
      // Storage may be blocked; the choice then lasts for this visit only.
    }
  }, []);
  return { columns, setColumns };
}
