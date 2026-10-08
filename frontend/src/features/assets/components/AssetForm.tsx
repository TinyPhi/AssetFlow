// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { useMemo, useRef, useState } from "react";
import { t } from "@/lib/i18n";
import { useMe } from "@/lib/permissions";
import { useCategoryRecords, useFieldDefinitions, useParties } from "../hooks/useCatalog";
import { useLocations, useOrgUnits } from "../hooks/useAssetLookups";
import { useVocabulary } from "../hooks/useAssetDetail";
import { humanizeKey } from "../lib/asset-filter-params";
import {
  coreErrors,
  coreFromAsset,
  customOutcome,
  customValuesFromAsset,
  EMPTY_CORE,
  encryptedIsSet,
  ownerOrLocationChanged,
  usableOrgUnits,
  type CoreValues,
} from "../lib/asset-form";
import type { FieldValue, FieldValues } from "../lib/custom-field-schema";
import { treeOrder } from "../lib/hierarchy";
import type { AssetDetail, HierarchyNode } from "../types";
import { BUTTON_CLASS, CONTROL_CLASS, PRIMARY_BUTTON_CLASS } from "./control-class";
import { CustomFieldInput } from "./CustomFieldInput";
import { HierarchySelect } from "./fields";
import { FormField } from "./FormField";

export interface AssetFormSubmit {
  core: CoreValues;
  /** The values the form started with (`null` on create). */
  initial: CoreValues | null;
  /** Typed custom values to send: all filled fields on create, changed ones on edit. */
  custom: Record<string, unknown>;
  moveComponents: boolean;
}

interface AssetFormProps {
  mode: "create" | "edit";
  /** The asset being edited. */
  asset?: AssetDetail;
  submitting: boolean;
  /** Field errors from a 422, keyed by field (`custom_fields.<key>` for a custom field). */
  serverErrors: Record<string, string>;
  /** A refusal that belongs to no field. */
  formError: string | null;
  onSubmit: (submit: AssetFormSubmit) => void;
  onCancel: () => void;
}

const NBSP = " ";

interface Option {
  value: string;
  label: string;
}

const SelectField: React.FC<{
  label: string;
  value: string;
  options: readonly Option[];
  emptyLabel: string;
  onChange: (value: string) => void;
  required?: boolean;
  error?: string | undefined;
}> = ({ label, value, options, emptyLabel, onChange, required = false, error }) => (
  <FormField label={label} required={required} error={error}>
    {(control) => (
      <select
        {...control}
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        className={CONTROL_CLASS}
      >
        <option value="">{emptyLabel}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    )}
  </FormField>
);

const TextField: React.FC<{
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "date";
  required?: boolean;
  inputMode?: "decimal";
  error?: string | undefined;
  maxLength?: number;
}> = ({ label, value, onChange, type = "text", required = false, inputMode, error, maxLength }) => (
  <FormField label={label} required={required} error={error}>
    {(control) => (
      <input
        {...control}
        type={type}
        value={value}
        {...(inputMode === undefined ? {} : { inputMode })}
        {...(maxLength === undefined ? {} : { maxLength })}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        className={CONTROL_CLASS}
      />
    )}
  </FormField>
);

/** Add the current value as an option when the list (active records only) no longer holds it. */
function withCurrent(options: Option[], id: string, name: string | null): Option[] {
  if (id === "" || options.some((option) => option.value === id)) return options;
  return [{ value: id, label: name ?? id }, ...options];
}

function indented(nodes: readonly HierarchyNode[]): Option[] {
  return treeOrder(nodes).map(({ node, depth }) => ({
    value: node.id,
    label: `${NBSP.repeat(depth * 3)}${node.name}`,
  }));
}

/**
 * The create and edit form (§B4.8.3, UF3). The category comes first on create and sets the custom fields and the
 * default criticality; an edit keeps the category. Every value is text until submit, when the Zod schemas turn it
 * into the API's body; an encrypted field is write-only ("set / not set") and is sent only when typed into.
 */
export const AssetForm: React.FC<AssetFormProps> = ({
  mode,
  asset,
  submitting,
  serverErrors,
  formError,
  onSubmit,
  onCancel,
}) => {
  const editing = mode === "edit" && asset !== undefined;
  const me = useMe();
  const categories = useCategoryRecords("active", mode === "create");
  const orgUnits = useOrgUnits();
  const locations = useLocations();
  const manufacturers = useParties("manufacturers", "active");
  const suppliers = useParties("suppliers", "active");
  const vocabulary = useVocabulary();

  const initial = useMemo(() => (editing ? coreFromAsset(asset) : null), [editing, asset]);
  const [core, setCore] = useState<CoreValues>(initial ?? EMPTY_CORE);
  const definitions = useFieldDefinitions(core.category_id, "active");
  const defs = useMemo(() => definitions.data ?? [], [definitions.data]);
  const [custom, setCustom] = useState<FieldValues>({});
  const [moveComponents, setMoveComponents] = useState(false);
  const [clientErrors, setClientErrors] = useState<Record<string, string>>({});
  const formRef = useRef<HTMLFormElement | null>(null);

  // On edit the definitions arrive after the first render: prefill the plain values from the asset once.
  const prefilled = useRef(false);
  if (editing && !prefilled.current && definitions.data !== undefined) {
    prefilled.current = true;
    setCustom(customValuesFromAsset(definitions.data, asset));
  }

  const set = <K extends keyof CoreValues>(key: K, value: CoreValues[K]): void => {
    setCore((prev) => ({ ...prev, [key]: value }));
  };

  const chooseCategory = (id: string): void => {
    const record = categories.data?.find((category) => category.id === id);
    setCore((prev) => ({
      ...prev,
      category_id: id,
      criticality: record?.default_criticality ?? "",
    }));
    setCustom({});
    setClientErrors({});
  };

  const permission = editing ? "asset.update" : "asset.create";
  const orgNodes = useMemo(() => {
    const usable = usableOrgUnits(orgUnits.data ?? [], me.data, permission);
    const current = orgUnits.data?.find((node) => node.id === core.owner_org_unit_id);
    return current !== undefined && !usable.some((node) => node.id === current.id)
      ? [...usable, current]
      : usable;
  }, [orgUnits.data, me.data, permission, core.owner_org_unit_id]);

  const levels = useMemo(() => {
    const known = new Set(vocabulary.data?.criticality ?? []);
    if (core.criticality !== "") known.add(core.criticality);
    return [...known].map((level) => ({ value: level, label: humanizeKey(level) }));
  }, [vocabulary.data, core.criticality]);

  const errors: Record<string, string> = { ...serverErrors, ...clientErrors };
  const customError = (key: string): string | undefined => errors[`custom_fields.${key}`] ?? errors[key];
  const showMove =
    editing && asset.component_count > 0 && initial !== null && ownerOrLocationChanged(initial, core);

  const submit = (): void => {
    const problems = coreErrors(core);
    const outcome = customOutcome(defs, custom, editing ? asset : null);
    const merged = {
      ...problems,
      ...Object.fromEntries(
        Object.entries(outcome.errors).map(([key, message]) => [`custom_fields.${key}`, message]),
      ),
    };
    setClientErrors(merged);
    if (Object.keys(merged).length > 0) {
      // Focus the first control that is now marked invalid, once it has rendered its state.
      setTimeout(() => {
        formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
      }, 0);
      return;
    }
    onSubmit({ core, initial, custom: outcome.data, moveComponents: showMove && moveComponents });
  };

  const categoryOptions = categories.data ?? [];

  return (
    <form
      ref={formRef}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      className="space-y-6"
    >
      {formError !== null && (
        <p role="alert" className="rounded-lg border border-danger p-3 text-sm text-danger">
          {formError}
        </p>
      )}

      <fieldset className="space-y-4">
        <legend className="text-base font-semibold">{t("assets.form.section_core")}</legend>
        {editing ? (
          <p className="text-sm">
            <span className="text-muted">{t("assets.form.category_fixed")} </span>
            <span className="font-medium">{asset.category_name}</span>
          </p>
        ) : (
          <HierarchySelect
            label={`${t("assets.form.category")} ${t("assets.form.required_mark")}`}
            emptyLabel={t("assets.form.choose_category")}
            nodes={categoryOptions}
            value={core.category_id}
            onChange={chooseCategory}
          />
        )}
        {errors["category_id"] !== undefined && (
          <p role="alert" className="text-xs font-medium text-danger">
            {errors["category_id"]}
          </p>
        )}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <TextField
            label={t("assets.form.name")}
            required
            maxLength={255}
            value={core.name}
            error={errors["name"]}
            onChange={(value) => {
              set("name", value);
            }}
          />
          <TextField
            label={t("assets.form.model")}
            maxLength={255}
            value={core.model}
            error={errors["model"]}
            onChange={(value) => {
              set("model", value);
            }}
          />
          <SelectField
            label={t("assets.form.manufacturer")}
            value={core.manufacturer_id}
            emptyLabel={t("assets.form.none_chosen")}
            options={withCurrent(
              (manufacturers.data ?? []).map((party) => ({ value: party.id, label: party.name })),
              core.manufacturer_id,
              asset?.manufacturer_name ?? null,
            )}
            error={errors["manufacturer_id"]}
            onChange={(value) => {
              set("manufacturer_id", value);
            }}
          />
          <SelectField
            label={t("assets.form.supplier")}
            value={core.supplier_id}
            emptyLabel={t("assets.form.none_chosen")}
            options={withCurrent(
              (suppliers.data ?? []).map((party) => ({ value: party.id, label: party.name })),
              core.supplier_id,
              asset?.supplier_name ?? null,
            )}
            error={errors["supplier_id"]}
            onChange={(value) => {
              set("supplier_id", value);
            }}
          />
          <TextField
            label={t("assets.form.serial_number")}
            maxLength={255}
            value={core.serial_number}
            error={errors["serial_number"]}
            onChange={(value) => {
              set("serial_number", value);
            }}
          />
          <SelectField
            label={t("assets.form.criticality")}
            value={core.criticality}
            emptyLabel={t("assets.form.category_default")}
            options={levels}
            error={errors["criticality"]}
            onChange={(value) => {
              set("criticality", value);
            }}
          />
          <SelectField
            label={t("assets.form.owner_org_unit")}
            required
            value={core.owner_org_unit_id}
            emptyLabel={t("assets.form.choose_org_unit")}
            options={indented(orgNodes)}
            error={errors["owner_org_unit_id"]}
            onChange={(value) => {
              set("owner_org_unit_id", value);
            }}
          />
          <SelectField
            label={t("assets.form.location")}
            value={core.location_id}
            emptyLabel={t("assets.form.none_chosen")}
            options={indented(locations.data ?? [])}
            error={errors["location_id"]}
            onChange={(value) => {
              set("location_id", value);
            }}
          />
          <TextField
            label={t("assets.form.purchase_date")}
            type="date"
            value={core.purchase_date}
            error={errors["purchase_date"]}
            onChange={(value) => {
              set("purchase_date", value);
            }}
          />
          <TextField
            label={t("assets.form.purchase_cost")}
            inputMode="decimal"
            value={core.purchase_cost}
            error={errors["purchase_cost"]}
            onChange={(value) => {
              set("purchase_cost", value);
            }}
          />
          <TextField
            label={t("assets.form.warranty_end")}
            type="date"
            value={core.warranty_end}
            error={errors["warranty_end"]}
            onChange={(value) => {
              set("warranty_end", value);
            }}
          />
        </div>

        <FormField label={t("assets.form.notes")} error={errors["notes"]}>
          {(control) => (
            <textarea
              {...control}
              value={core.notes}
              onChange={(event) => {
                set("notes", event.target.value);
              }}
              className={`${CONTROL_CLASS} h-auto min-h-24 py-2`}
            />
          )}
        </FormField>

        {showMove && (
          <label className="flex min-h-11 items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={moveComponents}
              onChange={(event) => {
                setMoveComponents(event.target.checked);
              }}
              className="h-5 w-5 accent-primary"
            />
            {t("assets.form.move_components")}
          </label>
        )}
      </fieldset>

      {core.category_id !== "" && (
        <fieldset className="space-y-4">
          <legend className="text-base font-semibold">{t("assets.form.section_custom")}</legend>
          {definitions.isPending && <p className="text-sm text-muted">{t("ui.state.loading")}</p>}
          {definitions.isError && (
            <p role="alert" className="text-sm text-danger">
              {t("assets.form.fields_failed")}
            </p>
          )}
          {definitions.data?.length === 0 && (
            <p className="text-sm text-muted">{t("assets.form.no_custom")}</p>
          )}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {defs.map((def) => {
              const stored: FieldValue = custom[def.key] ?? (def.field_type === "multi_select" ? [] : "");
              return (
                <CustomFieldInput
                  key={def.id}
                  def={def}
                  value={stored}
                  error={customError(def.key)}
                  {...(def.is_encrypted ? { isSet: encryptedIsSet(editing ? asset : null, def.key) } : {})}
                  onChange={(value) => {
                    setCustom((prev) => ({ ...prev, [def.key]: value }));
                  }}
                />
              );
            })}
          </div>
        </fieldset>
      )}

      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <button type="button" onClick={onCancel} className={BUTTON_CLASS}>
          {t("assets.form.cancel")}
        </button>
        <button type="submit" disabled={submitting} className={PRIMARY_BUTTON_CLASS}>
          {editing ? t("assets.form.save_changes") : t("assets.form.create")}
        </button>
      </div>
    </form>
  );
};
