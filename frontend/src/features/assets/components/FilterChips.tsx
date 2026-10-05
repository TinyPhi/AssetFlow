// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { X } from "lucide-react";
import type React from "react";
import { t, type TranslationKey } from "@/lib/i18n";
import { useCategories, useLocations, useOrgUnits, useTeams } from "../hooks/useAssetLookups";
import {
  activeChips,
  clearFilters,
  humanizeKey,
  removeChip,
  type AssetFilters,
  type ChipField,
  type FilterChip,
} from "../lib/asset-filter-params";
import { nodeName } from "../lib/hierarchy";
import { HOLDER_TYPE_OPTIONS, STATUS_CATEGORY_OPTIONS } from "../lib/asset-options";

const CHIP_LABELS: readonly { field: ChipField; labelKey: TranslationKey }[] = [
  { field: "status", labelKey: "assets.chips.status" },
  { field: "statusCategory", labelKey: "assets.chips.status_category" },
  { field: "categoryId", labelKey: "assets.chips.category" },
  { field: "ownerOrgUnitId", labelKey: "assets.chips.owner_org_unit" },
  { field: "locationId", labelKey: "assets.chips.location" },
  { field: "holderType", labelKey: "assets.chips.holder_type" },
  { field: "holderTeamId", labelKey: "assets.chips.holder_team" },
  { field: "criticality", labelKey: "assets.chips.criticality" },
  { field: "warrantyEndAfter", labelKey: "assets.chips.warranty_end_after" },
  { field: "warrantyEndBefore", labelKey: "assets.chips.warranty_end_before" },
  { field: "custom", labelKey: "assets.chips.custom" },
];

interface FilterChipsProps {
  filters: AssetFilters;
  onChange: (next: AssetFilters) => void;
}

/** The filters in force as removable chips, with a clear-all. */
export const FilterChips: React.FC<FilterChipsProps> = ({ filters, onChange }) => {
  const categories = useCategories();
  const orgUnits = useOrgUnits();
  const locations = useLocations();
  const teams = useTeams(filters.holderType === "team");
  const chips = activeChips(filters);
  if (chips.length === 0) return null;

  const valueLabel = (chip: FilterChip): string => {
    switch (chip.field) {
      case "categoryId":
        return nodeName(categories.data, chip.value);
      case "ownerOrgUnitId":
        return nodeName(orgUnits.data, chip.value);
      case "locationId":
        return nodeName(locations.data, chip.value);
      case "holderTeamId":
        return teams.data?.find((team) => team.id === chip.value)?.name ?? chip.value;
      case "holderType": {
        const option = HOLDER_TYPE_OPTIONS.find((o) => o.value === chip.value);
        return option === undefined ? chip.value : t(option.labelKey);
      }
      case "statusCategory": {
        const option = STATUS_CATEGORY_OPTIONS.find((o) => o.value === chip.value);
        return option === undefined ? chip.value : t(option.labelKey);
      }
      case "status":
      case "criticality":
        return humanizeKey(chip.value);
      case "custom":
        return `${chip.value.replace(/^cf\./, "")} = ${filters.custom[chip.value] ?? ""}`;
      case "warrantyEndAfter":
      case "warrantyEndBefore":
        return chip.value;
    }
  };

  return (
    <ul aria-label={t("assets.chips.label")} className="flex flex-wrap items-center gap-2">
      {chips.map((chip) => {
        const labelKey =
          CHIP_LABELS.find((entry) => entry.field === chip.field)?.labelKey ?? "assets.chips.custom";
        const label = t(labelKey, { value: valueLabel(chip) });
        return (
          <li key={chip.id}>
            <button
              type="button"
              onClick={() => {
                onChange(removeChip(filters, chip));
              }}
              aria-label={t("assets.chips.remove", { filter: label })}
              className="inline-flex min-h-11 max-w-full items-center gap-2 rounded-full border border-border bg-surface px-3 text-sm hover:bg-background focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
            >
              <span className="truncate">{label}</span>
              <X aria-hidden="true" className="h-4 w-4 shrink-0" />
            </button>
          </li>
        );
      })}
      <li>
        <button
          type="button"
          onClick={() => {
            onChange(clearFilters(filters));
          }}
          className="min-h-11 rounded-lg px-3 text-sm font-medium text-primary hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
        >
          {t("assets.chips.clear_all")}
        </button>
      </li>
    </ul>
  );
};
