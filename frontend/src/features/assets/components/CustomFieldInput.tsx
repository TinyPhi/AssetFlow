// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { t } from "@/lib/i18n";
import type { FieldValue } from "../lib/custom-field-schema";
import type { CustomFieldDefinition } from "../types";
import { CONTROL_CLASS } from "./control-class";
import { CheckGroup } from "./fields";
import { FormField } from "./FormField";

interface CustomFieldInputProps {
  def: CustomFieldDefinition;
  value: FieldValue;
  onChange: (value: FieldValue) => void;
  error?: string | undefined;
  /** An encrypted field only: whether the asset already holds a value (shown as "set / not set"). */
  isSet?: boolean;
}

const TEXTAREA_CLASS = `${CONTROL_CLASS} h-auto min-h-24 py-2`;

/** One input for one custom field, by its type (§B8.1): text, number, date, boolean, select, multi-select, json. */
export const CustomFieldInput: React.FC<CustomFieldInputProps> = ({ def, value, onChange, error, isSet }) => {
  const text = typeof value === "string" ? value : "";
  const set = (next: string): void => {
    onChange(next);
  };

  if (def.field_type === "multi_select") {
    return (
      <div className="min-w-0 space-y-1">
        <CheckGroup
          legend={def.is_required ? `${def.label} ${t("assets.form.required_mark")}` : def.label}
          options={def.rules.options.map((option) => ({ value: option, label: option }))}
          selected={typeof value === "string" ? [] : value}
          onChange={onChange}
        />
        {error !== undefined && (
          <p role="alert" className="text-xs font-medium text-danger">
            {error}
          </p>
        )}
      </div>
    );
  }

  const hint = def.is_encrypted
    ? isSet === true
      ? t("assets.form.encrypted_set")
      : t("assets.form.encrypted_not_set")
    : undefined;

  return (
    <FormField
      label={def.label}
      required={def.is_required}
      error={error}
      {...(hint === undefined ? {} : { hint })}
    >
      {(control) => {
        switch (def.field_type) {
          case "boolean":
            return (
              <select
                {...control}
                value={text}
                onChange={(event) => {
                  set(event.target.value);
                }}
                className={CONTROL_CLASS}
              >
                <option value="">{t("assets.form.not_chosen")}</option>
                <option value="true">{t("assets.filters.yes")}</option>
                <option value="false">{t("assets.filters.no")}</option>
              </select>
            );
          case "select":
            return (
              <select
                {...control}
                value={text}
                onChange={(event) => {
                  set(event.target.value);
                }}
                className={CONTROL_CLASS}
              >
                <option value="">{t("assets.form.not_chosen")}</option>
                {def.rules.options.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            );
          case "json":
            return (
              <textarea
                {...control}
                value={text}
                spellCheck={false}
                autoComplete="off"
                onChange={(event) => {
                  set(event.target.value);
                }}
                className={`${TEXTAREA_CLASS} font-mono`}
              />
            );
          case "date":
            return (
              <input
                {...control}
                type={def.is_encrypted ? "password" : "date"}
                autoComplete="off"
                value={text}
                onChange={(event) => {
                  set(event.target.value);
                }}
                className={CONTROL_CLASS}
              />
            );
          default:
            return (
              <input
                {...control}
                type={def.is_encrypted ? "password" : "text"}
                inputMode={def.field_type === "number" ? "decimal" : "text"}
                autoComplete={def.is_encrypted ? "new-password" : "off"}
                value={text}
                onChange={(event) => {
                  set(event.target.value);
                }}
                className={CONTROL_CLASS}
              />
            );
        }
      }}
    </FormField>
  );
};
