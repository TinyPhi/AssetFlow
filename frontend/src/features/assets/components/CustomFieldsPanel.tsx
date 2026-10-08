// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { useState } from "react";
import { useToast } from "@/app/toastContext";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { t, type TranslationKey } from "@/lib/i18n";
import { useFieldDefinitions, useFieldMutations } from "../hooks/useCatalog";
import {
  catalogFailure,
  EMPTY_FIELD,
  fieldCreateBody,
  fieldErrors,
  fieldUpdateBody,
  fieldValues,
  type FieldFormValues,
} from "../lib/catalog-form";
import type { CustomFieldDefinition, CustomFieldType } from "../types";
import { BUTTON_CLASS, CONTROL_CLASS, PRIMARY_BUTTON_CLASS } from "./control-class";
import { ConfirmDialog } from "./ConfirmDialog";
import { Dialog } from "./Dialog";
import { FormField } from "./FormField";

const TYPE_OPTIONS: readonly { value: CustomFieldType; labelKey: TranslationKey }[] = [
  { value: "text", labelKey: "assets.categories.type_text" },
  { value: "number", labelKey: "assets.categories.type_number" },
  { value: "date", labelKey: "assets.categories.type_date" },
  { value: "boolean", labelKey: "assets.categories.type_boolean" },
  { value: "select", labelKey: "assets.categories.type_select" },
  { value: "multi_select", labelKey: "assets.categories.type_multi_select" },
  { value: "json", labelKey: "assets.categories.type_json" },
];

function typeLabel(type: string): string {
  const option = TYPE_OPTIONS.find((candidate) => candidate.value === type) ?? TYPE_OPTIONS[0];
  return option === undefined ? type : t(option.labelKey);
}

type Action =
  | { kind: "create" }
  | { kind: "edit"; def: CustomFieldDefinition }
  | { kind: "archive"; def: CustomFieldDefinition };

const Check: React.FC<{
  label: string;
  checked: boolean;
  disabled?: boolean;
  error?: string | undefined;
  onChange: (checked: boolean) => void;
}> = ({ label, checked, disabled = false, error, onChange }) => (
  <div>
    <label className="flex min-h-11 items-center gap-2 text-sm">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => {
          onChange(event.target.checked);
        }}
        className="h-5 w-5 accent-primary"
      />
      {label}
    </label>
    {error !== undefined && (
      <p role="alert" className="text-xs font-medium text-danger">
        {error}
      </p>
    )}
  </div>
);

/** One category's custom field definitions: list, create, edit and archive (the key and "encrypted" are fixed). */
export const CustomFieldsPanel: React.FC<{ categoryId: string; categoryName: string }> = ({
  categoryId,
  categoryName,
}) => {
  const { showToast } = useToast();
  const [showArchived, setShowArchived] = useState(false);
  const fields = useFieldDefinitions(categoryId, showArchived ? "" : "active");
  const mutations = useFieldMutations(categoryId);
  const [action, setAction] = useState<Action | null>(null);
  const [values, setValues] = useState<FieldFormValues>(EMPTY_FIELD);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [failure, setFailure] = useState<string | null>(null);

  const close = (): void => {
    setAction(null);
    setErrors({});
    setFailure(null);
  };
  const open = (next: Action): void => {
    setErrors({});
    setFailure(null);
    if (next.kind === "create") setValues(EMPTY_FIELD);
    if (next.kind === "edit") setValues(fieldValues(next.def));
    setAction(next);
  };
  const done = (message: string): void => {
    close();
    showToast(message, "success");
  };
  const fail = (error: Error): void => {
    setFailure(catalogFailure(error));
  };
  const set = <K extends keyof FieldFormValues>(key: K, value: FieldFormValues[K]): void => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };

  const submit = (): void => {
    if (action === null || action.kind === "archive") return;
    const found = fieldErrors(values, action.kind);
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    if (action.kind === "create") {
      mutations.create.mutate(fieldCreateBody(values), {
        onSuccess: () => {
          done(t("assets.categories.field_created"));
        },
        onError: fail,
      });
      return;
    }
    mutations.update.mutate(
      { id: action.def.id, input: fieldUpdateBody(fieldValues(action.def), values, action.def.version) },
      {
        onSuccess: () => {
          done(t("assets.categories.field_saved"));
        },
        onError: fail,
      },
    );
  };

  const type = values.field_type;
  const bounds = type === "text" || type === "number";
  const editing = action?.kind === "edit";

  let body: React.ReactNode;
  if (fields.isPending) body = <Skeleton rows={3} />;
  else if (fields.isError) {
    body = (
      <ErrorState
        message={t("assets.categories.fields_load_failed")}
        onRetry={() => {
          void fields.refetch();
        }}
      />
    );
  } else if (fields.data.length === 0) {
    body = <EmptyState title={t("assets.categories.fields_empty")} />;
  } else {
    body = (
      <ul aria-label={t("assets.categories.fields_list")} className="space-y-2">
        {fields.data.map((def) => (
          <li
            key={def.id}
            className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-3 sm:flex-row sm:items-center sm:justify-between"
          >
            <div className="min-w-0">
              <p className="break-words font-semibold">{def.label}</p>
              <p className="text-xs text-muted">
                <span className="font-mono">{def.key}</span>
                {` · ${typeLabel(def.field_type)}`}
                {def.is_required && ` · ${t("assets.categories.required")}`}
                {def.is_encrypted && ` · ${t("assets.categories.encrypted")}`}
                {def.status === "archived" && ` · ${t("assets.categories.archived")}`}
              </p>
            </div>
            {def.status !== "archived" && (
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  aria-label={t("assets.categories.field_edit_named", { name: def.label })}
                  onClick={() => {
                    open({ kind: "edit", def });
                  }}
                  className={BUTTON_CLASS}
                >
                  {t("assets.categories.edit")}
                </button>
                <button
                  type="button"
                  aria-label={t("assets.categories.field_archive_named", { name: def.label })}
                  onClick={() => {
                    open({ kind: "archive", def });
                  }}
                  className={BUTTON_CLASS}
                >
                  {t("assets.categories.archive")}
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
    );
  }

  return (
    <section aria-labelledby="fields-heading" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="fields-heading" className="text-lg font-semibold">
          {t("assets.categories.fields_title", { name: categoryName })}
        </h2>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex min-h-11 items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={showArchived}
              onChange={(event) => {
                setShowArchived(event.target.checked);
              }}
              className="h-5 w-5 accent-primary"
            />
            {t("assets.categories.show_archived")}
          </label>
          <button
            type="button"
            onClick={() => {
              open({ kind: "create" });
            }}
            className={PRIMARY_BUTTON_CLASS}
          >
            {t("assets.categories.field_new")}
          </button>
        </div>
      </div>
      {body}

      {(action?.kind === "create" || action?.kind === "edit") && (
        <Dialog
          title={
            action.kind === "create"
              ? t("assets.categories.field_new")
              : t("assets.categories.field_edit_title")
          }
          onClose={close}
        >
          <form
            noValidate
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              submit();
            }}
          >
            <FormField
              label={t("assets.categories.field_key")}
              required={!editing}
              error={errors["key"]}
              hint={t("assets.categories.field_key_hint")}
            >
              {(control) => (
                <input
                  {...control}
                  type="text"
                  value={values.key}
                  disabled={editing}
                  onChange={(event) => {
                    set("key", event.target.value);
                  }}
                  className={CONTROL_CLASS}
                />
              )}
            </FormField>
            <FormField label={t("assets.categories.field_label")} required error={errors["label"]}>
              {(control) => (
                <input
                  {...control}
                  type="text"
                  value={values.label}
                  maxLength={255}
                  onChange={(event) => {
                    set("label", event.target.value);
                  }}
                  className={CONTROL_CLASS}
                />
              )}
            </FormField>
            <FormField label={t("assets.categories.field_type")}>
              {(control) => (
                <select
                  {...control}
                  value={type}
                  onChange={(event) => {
                    set("field_type", event.target.value);
                  }}
                  className={CONTROL_CLASS}
                >
                  {TYPE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {t(option.labelKey)}
                    </option>
                  ))}
                </select>
              )}
            </FormField>
            {bounds && (
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <FormField
                  label={
                    type === "text" ? t("assets.categories.min_length") : t("assets.categories.min_value")
                  }
                  error={errors["min"]}
                >
                  {(control) => (
                    <input
                      {...control}
                      type="text"
                      inputMode="decimal"
                      value={values.min}
                      onChange={(event) => {
                        set("min", event.target.value);
                      }}
                      className={CONTROL_CLASS}
                    />
                  )}
                </FormField>
                <FormField
                  label={
                    type === "text" ? t("assets.categories.max_length") : t("assets.categories.max_value")
                  }
                  error={errors["max"]}
                >
                  {(control) => (
                    <input
                      {...control}
                      type="text"
                      inputMode="decimal"
                      value={values.max}
                      onChange={(event) => {
                        set("max", event.target.value);
                      }}
                      className={CONTROL_CLASS}
                    />
                  )}
                </FormField>
              </div>
            )}
            {type === "text" && (
              <FormField label={t("assets.categories.regex")} error={errors["regex"]}>
                {(control) => (
                  <input
                    {...control}
                    type="text"
                    value={values.regex}
                    spellCheck={false}
                    onChange={(event) => {
                      set("regex", event.target.value);
                    }}
                    className={`${CONTROL_CLASS} font-mono`}
                  />
                )}
              </FormField>
            )}
            {(type === "select" || type === "multi_select") && (
              <FormField
                label={t("assets.categories.options")}
                required
                error={errors["optionsText"]}
                hint={t("assets.categories.options_hint")}
              >
                {(control) => (
                  <textarea
                    {...control}
                    value={values.optionsText}
                    onChange={(event) => {
                      set("optionsText", event.target.value);
                    }}
                    className={`${CONTROL_CLASS} h-auto min-h-24 py-2`}
                  />
                )}
              </FormField>
            )}
            <FormField label={t("assets.categories.position")} error={errors["position"]}>
              {(control) => (
                <input
                  {...control}
                  type="text"
                  inputMode="numeric"
                  value={values.position}
                  onChange={(event) => {
                    set("position", event.target.value);
                  }}
                  className={CONTROL_CLASS}
                />
              )}
            </FormField>
            <Check
              label={t("assets.categories.is_required")}
              checked={values.is_required}
              onChange={(checked) => {
                set("is_required", checked);
              }}
            />
            <Check
              label={t("assets.categories.is_unique")}
              checked={values.is_unique}
              error={errors["is_unique"]}
              onChange={(checked) => {
                set("is_unique", checked);
              }}
            />
            <Check
              label={t("assets.categories.is_encrypted")}
              checked={values.is_encrypted}
              disabled={editing}
              onChange={(checked) => {
                set("is_encrypted", checked);
              }}
            />
            {failure !== null && (
              <p role="alert" className="text-sm text-danger">
                {failure}
              </p>
            )}
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" onClick={close} className={BUTTON_CLASS}>
                {t("assets.form.cancel")}
              </button>
              <button
                type="submit"
                disabled={mutations.create.isPending || mutations.update.isPending}
                className={PRIMARY_BUTTON_CLASS}
              >
                {action.kind === "create"
                  ? t("assets.categories.field_create")
                  : t("assets.form.save_changes")}
              </button>
            </div>
          </form>
        </Dialog>
      )}

      {action?.kind === "archive" && (
        <ConfirmDialog
          title={t("assets.categories.field_archive_title", { name: action.def.label })}
          body={t("assets.categories.field_archive_body")}
          confirmLabel={t("assets.categories.archive")}
          pending={mutations.archive.isPending}
          error={failure}
          onClose={close}
          onConfirm={() => {
            mutations.archive.mutate(
              { id: action.def.id, version: action.def.version },
              {
                onSuccess: () => {
                  done(t("assets.categories.field_archived_done"));
                },
                onError: fail,
              },
            );
          }}
        />
      )}
    </section>
  );
};
