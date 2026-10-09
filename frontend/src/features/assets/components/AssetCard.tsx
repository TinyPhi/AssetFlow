// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { t } from "@/lib/i18n";
import type { AssetListItem } from "../types";
import { AssetCell } from "./AssetCells";

/** One asset as a card (below 1024 px): tag, name, status pill, holder and owner org unit. */
export const AssetCard: React.FC<{ item: AssetListItem }> = ({ item }) => (
  <li className="min-w-0 rounded-xl border border-border bg-surface p-4">
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <p className="text-muted">
          <AssetCell column="tag" item={item} />
        </p>
        <p className="mt-0.5 break-words text-base">
          <AssetCell column="name" item={item} />
        </p>
      </div>
      <AssetCell column="status" item={item} />
    </div>
    <dl className="mt-3 space-y-1 text-sm">
      <div className="flex justify-between gap-4">
        <dt className="text-muted">{t("assets.columns.holder")}</dt>
        <dd className="min-w-0 break-words text-right">
          <AssetCell column="holder" item={item} />
        </dd>
      </div>
      <div className="flex justify-between gap-4">
        <dt className="text-muted">{t("assets.columns.owner_org_unit_name")}</dt>
        <dd className="min-w-0 break-words text-right">
          <AssetCell column="owner_org_unit_name" item={item} />
        </dd>
      </div>
    </dl>
  </li>
);
