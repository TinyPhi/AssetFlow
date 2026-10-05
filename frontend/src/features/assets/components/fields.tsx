// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { useId } from "react";
import { t } from "@/lib/i18n";
import { treeOrder } from "../lib/hierarchy";
import type { HierarchyNode } from "../types";
import { CONTROL_CLASS } from "./control-class";

const NBSP = " ";

interface FieldProps {
  label: string;
  children: (id: string) => React.ReactNode;
}

/** A labelled control: the label is tied to the control by id. */
export const Field: React.FC<FieldProps> = ({ label, children }) => {
  const id = useId();
  return (
    <div className="min-w-0 space-y-1">
      <label htmlFor={id} className="block text-xs font-medium text-muted">
        {label}
      </label>
      {children(id)}
    </div>
  );
};

interface HierarchySelectProps {
  label: string;
  nodes: readonly HierarchyNode[];
  value: string;
  onChange: (id: string) => void;
  /** The "include sub-…" switch shown once something is chosen. */
  /** The empty option's text; defaults to "Any" (a filter). A form passes its own prompt. */
  emptyLabel?: string;
  includeLabel?: string;
  includeChecked?: boolean;
  onIncludeChange?: (checked: boolean) => void;
}

/** A tree picker as a native select with indented options (keyboard and screen-reader friendly). */
export const HierarchySelect: React.FC<HierarchySelectProps> = ({
  label,
  nodes,
  value,
  onChange,
  emptyLabel,
  includeLabel,
  includeChecked = false,
  onIncludeChange,
}) => (
  <div className="min-w-0 space-y-1">
    <Field label={label}>
      {(id) => (
        <select
          id={id}
          value={value}
          onChange={(event) => {
            onChange(event.target.value);
          }}
          className={CONTROL_CLASS}
        >
          <option value="">{emptyLabel ?? t("assets.filters.any")}</option>
          {treeOrder(nodes).map(({ node, depth }) => (
            <option key={node.id} value={node.id}>
              {NBSP.repeat(depth * 3)}
              {node.name}
            </option>
          ))}
        </select>
      )}
    </Field>
    {value !== "" && includeLabel !== undefined && onIncludeChange !== undefined && (
      <label className="flex min-h-11 items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={includeChecked}
          onChange={(event) => {
            onIncludeChange(event.target.checked);
          }}
          className="h-5 w-5 accent-primary"
        />
        {includeLabel}
      </label>
    )}
  </div>
);

interface CheckGroupProps {
  legend: string;
  options: readonly { value: string; label: string }[];
  selected: readonly string[];
  onChange: (next: string[]) => void;
}

/** A multi-select as a group of checkboxes (each a 44 px touch target). */
export const CheckGroup: React.FC<CheckGroupProps> = ({ legend, options, selected, onChange }) => (
  <fieldset className="min-w-0 space-y-1">
    <legend className="text-xs font-medium text-muted">{legend}</legend>
    {options.length === 0 ? (
      <p className="text-sm text-muted">{t("assets.filters.no_options")}</p>
    ) : (
      <div className="flex flex-wrap gap-x-4">
        {options.map((option) => (
          <label key={option.value} className="flex min-h-11 items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={selected.includes(option.value)}
              onChange={(event) => {
                onChange(
                  event.target.checked
                    ? [...selected, option.value]
                    : selected.filter((value) => value !== option.value),
                );
              }}
              className="h-5 w-5 accent-primary"
            />
            {option.label}
          </label>
        ))}
      </div>
    )}
  </fieldset>
);
