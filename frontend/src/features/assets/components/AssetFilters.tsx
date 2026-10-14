// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { t } from "@/lib/i18n";
import {
  useCategories,
  useFilterableFields,
  useLocations,
  useOrgUnits,
  useTeams,
} from "../hooks/useAssetLookups";
import { humanizeKey, normalizeFilters, type AssetFilters as Filters } from "../lib/asset-filter-params";
import { HOLDER_TYPE_OPTIONS, STATUS_CATEGORY_OPTIONS } from "../lib/asset-options";
import type { CustomFieldDefinition } from "../types";
import { CONTROL_CLASS } from "./control-class";
import { CheckGroup, Field, HierarchySelect } from "./fields";

interface AssetFiltersProps {
  filters: Filters;
  onChange: (next: Filters) => void;
  /** Status and criticality values seen in the results so far: the API serves no list of them yet. */
  knownStatuses: readonly string[];
  knownCriticality: readonly string[];
}

function options(values: readonly string[], selected: readonly string[]): { value: string; label: string }[] {
  return [...new Set([...values, ...selected])].sort().map((value) => ({ value, label: humanizeKey(value) }));
}

const CustomFieldInputs: React.FC<{
  definition: CustomFieldDefinition;
  filters: Filters;
  onChange: (next: Filters) => void;
}> = ({ definition, filters, onChange }) => {
  const base = `cf.${definition.key}`;
  const set = (param: string, value: string): void => {
    onChange({ ...filters, custom: { ...filters.custom, [param]: value } });
  };
  const ranged = definition.field_type === "number" || definition.field_type === "date";
  const inputType =
    definition.field_type === "date" ? "date" : definition.field_type === "number" ? "number" : "text";
  if (definition.field_type === "boolean") {
    return (
      <Field label={definition.label}>
        {(id) => (
          <select
            id={id}
            value={filters.custom[base] ?? ""}
            onChange={(event) => {
              set(base, event.target.value);
            }}
            className={CONTROL_CLASS}
          >
            <option value="">{t("assets.filters.any")}</option>
            <option value="true">{t("assets.filters.yes")}</option>
            <option value="false">{t("assets.filters.no")}</option>
          </select>
        )}
      </Field>
    );
  }
  if (!ranged) {
    return (
      <Field label={definition.label}>
        {(id) => (
          <input
            id={id}
            type="text"
            value={filters.custom[base] ?? ""}
            onChange={(event) => {
              set(base, event.target.value);
            }}
            className={CONTROL_CLASS}
          />
        )}
      </Field>
    );
  }
  return (
    <>
      <Field label={t("assets.filters.custom_from", { field: definition.label })}>
        {(id) => (
          <input
            id={id}
            type={inputType}
            value={filters.custom[`${base}.gte`] ?? ""}
            onChange={(event) => {
              set(`${base}.gte`, event.target.value);
            }}
            className={CONTROL_CLASS}
          />
        )}
      </Field>
      <Field label={t("assets.filters.custom_to", { field: definition.label })}>
        {(id) => (
          <input
            id={id}
            type={inputType}
            value={filters.custom[`${base}.lte`] ?? ""}
            onChange={(event) => {
              set(`${base}.lte`, event.target.value);
            }}
            className={CONTROL_CLASS}
          />
        )}
      </Field>
    </>
  );
};

/** The filter controls: every change goes up as a whole new filter set, which the page writes to the URL. */
export const AssetFilters: React.FC<AssetFiltersProps> = ({
  filters,
  onChange,
  knownStatuses,
  knownCriticality,
}) => {
  const categories = useCategories();
  const orgUnits = useOrgUnits();
  const locations = useLocations();
  const teams = useTeams(filters.holderType === "team");
  const fields = useFilterableFields(filters.categoryId);
  const update = (patch: Partial<Filters>): void => {
    onChange(normalizeFilters({ ...filters, ...patch }));
  };

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      <HierarchySelect
        label={t("assets.filters.category")}
        nodes={categories.data ?? []}
        value={filters.categoryId}
        onChange={(categoryId) => {
          update({ categoryId, custom: {} });
        }}
        includeLabel={t("assets.filters.include_subcategories")}
        includeChecked={filters.includeSubcategories}
        onIncludeChange={(includeSubcategories) => {
          update({ includeSubcategories });
        }}
      />
      <HierarchySelect
        label={t("assets.filters.owner_org_unit")}
        nodes={orgUnits.data ?? []}
        value={filters.ownerOrgUnitId}
        onChange={(ownerOrgUnitId) => {
          update({ ownerOrgUnitId });
        }}
        includeLabel={t("assets.filters.include_sub_units")}
        includeChecked={filters.includeSubUnits}
        onIncludeChange={(includeSubUnits) => {
          update({ includeSubUnits });
        }}
      />
      <HierarchySelect
        label={t("assets.filters.location")}
        nodes={locations.data ?? []}
        value={filters.locationId}
        onChange={(locationId) => {
          update({ locationId });
        }}
        includeLabel={t("assets.filters.include_sub_locations")}
        includeChecked={filters.includeSubLocations}
        onIncludeChange={(includeSubLocations) => {
          update({ includeSubLocations });
        }}
      />
      <Field label={t("assets.filters.status_category")}>
        {(id) => (
          <select
            id={id}
            value={filters.statusCategory}
            onChange={(event) => {
              update({ statusCategory: event.target.value });
            }}
            className={CONTROL_CLASS}
          >
            <option value="">{t("assets.filters.any")}</option>
            {STATUS_CATEGORY_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {t(option.labelKey)}
              </option>
            ))}
          </select>
        )}
      </Field>
      <Field label={t("assets.filters.holder_type")}>
        {(id) => (
          <select
            id={id}
            value={filters.holderType}
            onChange={(event) => {
              const value = event.target.value;
              const holderType = HOLDER_TYPE_OPTIONS.find((option) => option.value === value)?.value ?? "";
              update({ holderType });
            }}
            className={CONTROL_CLASS}
          >
            <option value="">{t("assets.filters.any")}</option>
            {HOLDER_TYPE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {t(option.labelKey)}
              </option>
            ))}
          </select>
        )}
      </Field>
      {filters.holderType === "team" && (
        <Field label={t("assets.filters.holder_team")}>
          {(id) => (
            <select
              id={id}
              value={filters.holderTeamId}
              onChange={(event) => {
                update({ holderTeamId: event.target.value });
              }}
              className={CONTROL_CLASS}
            >
              <option value="">{t("assets.filters.any")}</option>
              {(teams.data ?? []).map((team) => (
                <option key={team.id} value={team.id}>
                  {team.name}
                </option>
              ))}
            </select>
          )}
        </Field>
      )}
      <Field label={t("assets.filters.warranty_end_after")}>
        {(id) => (
          <input
            id={id}
            type="date"
            value={filters.warrantyEndAfter}
            onChange={(event) => {
              update({ warrantyEndAfter: event.target.value });
            }}
            className={CONTROL_CLASS}
          />
        )}
      </Field>
      <Field label={t("assets.filters.warranty_end_before")}>
        {(id) => (
          <input
            id={id}
            type="date"
            value={filters.warrantyEndBefore}
            onChange={(event) => {
              update({ warrantyEndBefore: event.target.value });
            }}
            className={CONTROL_CLASS}
          />
        )}
      </Field>
      <div className="sm:col-span-2 xl:col-span-3">
        <CheckGroup
          legend={t("assets.filters.status")}
          options={options(knownStatuses, filters.status)}
          selected={filters.status}
          onChange={(status) => {
            update({ status });
          }}
        />
      </div>
      <div className="sm:col-span-2 xl:col-span-3">
        <CheckGroup
          legend={t("assets.filters.criticality")}
          options={options(knownCriticality, filters.criticality)}
          selected={filters.criticality}
          onChange={(criticality) => {
            update({ criticality });
          }}
        />
      </div>
      {(fields.data ?? []).map((definition) => (
        <CustomFieldInputs
          key={definition.id}
          definition={definition}
          filters={filters}
          onChange={onChange}
        />
      ))}
    </div>
  );
};
