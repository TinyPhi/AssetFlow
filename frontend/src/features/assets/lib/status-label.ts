// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type { Vocabulary } from "../types";
import { humanizeKey } from "./asset-filter-params";

/** The template's label for a status key; the key made readable while the vocabulary has not loaded. */
export function statusLabel(vocabulary: Vocabulary | undefined, key: string): string {
  return vocabulary?.statuses.find((status) => status.key === key)?.label ?? humanizeKey(key);
}
