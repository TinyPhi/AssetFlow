// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { useId } from "react";
import { t } from "@/lib/i18n";

export interface ControlProps {
  id: string;
  "aria-invalid": boolean;
  "aria-describedby": string | undefined;
  "aria-required": boolean;
}

interface FormFieldProps {
  label: string;
  required?: boolean;
  hint?: string;
  error?: string | undefined;
  children: (props: ControlProps) => React.ReactNode;
}

/** A labelled control with an optional hint and error; the error is tied to the control and announced. */
export const FormField: React.FC<FormFieldProps> = ({ label, required = false, hint, error, children }) => {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [hint === undefined ? null : hintId, error === undefined ? null : errorId]
    .filter((part): part is string => part !== null)
    .join(" ");
  return (
    <div className="min-w-0 space-y-1">
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
        {required && (
          <>
            <span aria-hidden="true" className="text-danger">
              {" *"}
            </span>
            <span className="sr-only">{t("assets.form.required_suffix")}</span>
          </>
        )}
      </label>
      {children({
        id,
        "aria-invalid": error !== undefined,
        "aria-describedby": describedBy === "" ? undefined : describedBy,
        "aria-required": required,
      })}
      {hint !== undefined && (
        <p id={hintId} className="text-xs text-muted">
          {hint}
        </p>
      )}
      {error !== undefined && (
        <p id={errorId} role="alert" className="text-xs font-medium text-danger">
          {error}
        </p>
      )}
    </div>
  );
};
