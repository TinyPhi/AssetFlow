// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

export interface JSONSchemaProperty {
  type?: string;
  title?: string;
  description?: string;
  format?: string;
  enum?: string[];
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  items?: JSONSchemaProperty;
  properties?: Record<string, JSONSchemaProperty>;
  required?: string[];
  "x-assetflow-secret"?: boolean;
}

export interface JSONSchemaRoot {
  type?: string;
  title?: string;
  description?: string;
  properties?: Record<string, JSONSchemaProperty>;
  required?: string[];
}

export function validateJSONSchema(
  schema: JSONSchemaRoot,
  data: Record<string, unknown>,
): Record<string, string> {
  const errors: Record<string, string> = {};
  const properties = schema.properties ?? {};
  const required = new Set(schema.required ?? []);

  for (const [key, prop] of Object.entries(properties)) {
    const val = data[key];

    if (required.has(key) && (val === undefined || val === null || val === "")) {
      errors[key] = "This field is required.";
      continue;
    }

    if (val === undefined || val === null || val === "") continue;

    if (prop.type === "string") {
      const s = typeof val === "string" ? val : "";
      if (prop.minLength !== undefined && s.length < prop.minLength) {
        errors[key] = `Must be at least ${String(prop.minLength)} characters.`;
      }
      if (prop.maxLength !== undefined && s.length > prop.maxLength) {
        errors[key] = `Must be at most ${String(prop.maxLength)} characters.`;
      }
      if (prop.format === "email" && !s.includes("@")) {
        errors[key] = "Must be a valid email address.";
      }
      if (prop.format === "uri" && !s.startsWith("http://") && !s.startsWith("https://")) {
        errors[key] = "Must be a valid HTTP or HTTPS URL.";
      }
    } else if (prop.type === "integer" || prop.type === "number") {
      const n = Number(val);
      if (Number.isNaN(n)) {
        errors[key] = "Must be a valid number.";
      } else {
        if (prop.minimum !== undefined && n < prop.minimum) {
          errors[key] = `Must be at least ${String(prop.minimum)}.`;
        }
        if (prop.maximum !== undefined && n > prop.maximum) {
          errors[key] = `Must be at most ${String(prop.maximum)}.`;
        }
      }
    }
  }

  return errors;
}
