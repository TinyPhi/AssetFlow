// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { Link } from "react-router";
import { t, useFormat } from "@/lib/i18n";
import type { ColumnId } from "../lib/asset-columns";
import { humanizeKey } from "../lib/asset-filter-params";
import { holderTypeLabelKey } from "../lib/asset-options";
import type { AssetHolder, AssetListItem } from "../types";

/** The status as a pill. The label is the status key made readable: the API serves no label yet. */
export const StatusPill: React.FC<{ status: string }> = ({ status }) => (
  <span className="inline-flex max-w-full items-center rounded-full border border-border bg-background px-2.5 py-0.5 text-xs font-medium text-foreground">
    <span className="truncate">{humanizeKey(status)}</span>
  </span>
);

export const HolderCell: React.FC<{ holder: AssetHolder | null }> = ({ holder }) => {
  if (holder === null) return <span className="text-muted">{t("assets.list.no_holder")}</span>;
  return (
    <span className="break-words">
      {holder.display_name}
      <span className="ml-1 text-xs text-muted">
        {t("assets.list.holder_type_suffix", { type: t(holderTypeLabelKey(holder.type)) })}
      </span>
    </span>
  );
};

/** One cell's content, shared by the table and the cards so both show the same thing. */
export const AssetCell: React.FC<{ column: ColumnId; item: AssetListItem }> = ({ column, item }) => {
  const { formatDate, formatDateTime } = useFormat();
  const text = (value: string | null): React.ReactNode =>
    value === null || value === "" ? (
      <span className="text-muted">{t("assets.list.empty_value")}</span>
    ) : (
      value
    );
  switch (column) {
    case "tag":
      return <span className="font-mono text-xs">{item.tag}</span>;
    case "name":
      return (
        <Link
          to={`/assets/${item.id}`}
          className="inline-flex min-h-11 min-w-11 items-center font-semibold text-primary underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
        >
          {item.name}
        </Link>
      );
    case "status":
      return <StatusPill status={item.status} />;
    case "category_name":
      return <>{text(item.category_name)}</>;
    case "holder":
      return <HolderCell holder={item.holder} />;
    case "owner_org_unit_name":
      return <>{text(item.owner_org_unit_name)}</>;
    case "location_name":
      return <>{text(item.location_name)}</>;
    case "criticality":
      return <>{text(item.criticality === null ? null : humanizeKey(item.criticality))}</>;
    case "warranty_end":
      return (
        <>{text(item.warranty_end === null ? null : formatDate(item.warranty_end, { timeZone: "UTC" }))}</>
      );
    case "model":
      return <>{text(item.model)}</>;
    case "serial_number":
      return <>{text(item.serial_number)}</>;
    case "updated_at":
      return <>{text(item.updated_at === "" ? null : formatDateTime(item.updated_at))}</>;
  }
};
