// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { useState } from "react";
import { type JSONSchemaRoot, validateJSONSchema } from "./jsonSchemaToZod";

interface SchemaFormProps {
  schema: JSONSchemaRoot;
  initialValues?: Record<string, unknown>;
  onSubmit: (values: Record<string, unknown>) => Promise<void> | void;
  submitLabel?: string;
  isSubmitting?: boolean;
}

export const SchemaForm: React.FC<SchemaFormProps> = ({
  schema,
  initialValues = {},
  onSubmit,
  submitLabel = "Save Configuration",
  isSubmitting = false,
}) => {
  const [formData, setFormData] = useState<Record<string, unknown>>(initialValues);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const properties = schema.properties ?? {};
  const required = new Set(schema.required ?? []);

  const handleChange = (key: string, value: unknown) => {
    setFormData((prev) => ({ ...prev, [key]: value }));
    if (errors[key]) {
      setErrors((prev) => {
        const next = { ...prev };
        Reflect.deleteProperty(next, key);
        return next;
      });
    }
  };

  const handleSubmit = async (e: React.SyntheticEvent) => {
    e.preventDefault();
    const validationErrors = validateJSONSchema(schema, formData);
    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors);
      return;
    }
    await onSubmit(formData);
  };

  return (
    <form
      onSubmit={(e) => {
        void handleSubmit(e);
      }}
      className="space-y-5"
    >
      {Object.entries(properties).map(([key, prop]) => {
        const isRequired = required.has(key);
        const isSecret = prop["x-assetflow-secret"] === true || prop.format === "password";
        const error = errors[key];
        const val = formData[key];
        const strVal =
          typeof val === "string" || typeof val === "number" || typeof val === "boolean" ? String(val) : "";

        return (
          <div key={key} className="space-y-1.5">
            <label htmlFor={`field-${key}`} className="block text-sm font-medium text-foreground">
              {prop.title ?? key}
              {isRequired && <span className="ml-1 text-danger">{"*"}</span>}
            </label>

            {prop.description && <p className="text-xs text-muted">{prop.description}</p>}

            {prop.type === "boolean" ? (
              <div className="flex items-center gap-2 pt-1">
                <input
                  type="checkbox"
                  id={`field-${key}`}
                  checked={Boolean(val)}
                  onChange={(e) => {
                    handleChange(key, e.target.checked);
                  }}
                  className="h-4 w-4 rounded border-border text-primary focus:ring-primary"
                />
                <span className="text-xs text-muted">{"Enable"}</span>
              </div>
            ) : prop.enum && prop.enum.length > 0 ? (
              <select
                id={`field-${key}`}
                value={strVal}
                onChange={(e) => {
                  handleChange(key, e.target.value);
                }}
                className="flex h-11 w-full rounded-lg border border-border bg-surface px-3 text-sm text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
              >
                <option value="">{"Select option…"}</option>
                {prop.enum.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>
            ) : (
              <input
                id={`field-${key}`}
                type={
                  isSecret
                    ? "password"
                    : prop.type === "integer" || prop.type === "number"
                      ? "number"
                      : "text"
                }
                value={strVal}
                onChange={(e) => {
                  const v =
                    prop.type === "integer" || prop.type === "number"
                      ? e.target.value === ""
                        ? ""
                        : Number(e.target.value)
                      : e.target.value;
                  handleChange(key, v);
                }}
                placeholder={isSecret ? "••••••••" : `Enter ${prop.title ?? key}`}
                className={`flex h-11 w-full rounded-lg border bg-surface px-3 text-sm text-foreground placeholder:text-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus ${
                  error ? "border-danger" : "border-border"
                }`}
              />
            )}

            {error && <p className="text-xs font-medium text-danger">{error}</p>}
          </div>
        );
      })}

      <div className="pt-2">
        <button
          type="submit"
          disabled={isSubmitting}
          className="inline-flex min-h-11 items-center justify-center rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm hover:opacity-90 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
        >
          {isSubmitting ? "Saving…" : submitLabel}
        </button>
      </div>
    </form>
  );
};
