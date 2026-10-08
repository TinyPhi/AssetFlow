// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { Link } from "react-router";
import { t, useFormat } from "@/lib/i18n";
import { useFieldDefinitions } from "../hooks/useCatalog";
import { humanizeKey } from "../lib/asset-filter-params";
import type { AssetDetail, CustomFieldDefinition } from "../types";
import { HolderCell } from "./AssetCells";

const EMPTY = <span className="text-muted">{t("assets.list.empty_value")}</span>;

function Row({ label, children }: { label: string; children: React.ReactNode }): React.ReactElement {
  return (
    <div className="grid grid-cols-1 gap-1 py-2 sm:grid-cols-3 sm:gap-4">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="min-w-0 break-words text-sm sm:col-span-2">{children}</dd>
    </div>
  );
}

function scalar(value: unknown): string {
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean"
    ? String(value)
    : JSON.stringify(value);
}

/** A custom field's value as text; a missing value is the "none" marker. */
function CustomValue({
  def,
  value,
  formatDate,
}: {
  def: CustomFieldDefinition;
  value: unknown;
  formatDate: (value: string, options: { timeZone: string }) => string;
}): React.ReactElement {
  if (value === null || value === undefined || value === "") return EMPTY;
  switch (def.field_type) {
    case "boolean":
      return <>{value === true ? t("assets.filters.yes") : t("assets.filters.no")}</>;
    case "date":
      return <>{typeof value === "string" ? formatDate(value, { timeZone: "UTC" }) : scalar(value)}</>;
    case "multi_select":
      return <>{Array.isArray(value) ? (value as unknown[]).map(scalar).join(", ") : scalar(value)}</>;
    case "json":
      return (
        <pre className="max-w-full overflow-x-auto whitespace-pre-wrap break-words rounded-lg bg-background p-2 font-mono text-xs">
          {JSON.stringify(value, null, 2)}
        </pre>
      );
    default:
      return <>{scalar(value)}</>;
  }
}

/** The Details tab: core fields, then the category's custom fields (encrypted ones as "set" or the revealed value). */
export const AssetDetails: React.FC<{ asset: AssetDetail }> = ({ asset }) => {
  const { formatDate, formatDateTime } = useFormat();
  const fields = useFieldDefinitions(asset.category_id, "");
  const date = (value: string | null): React.ReactNode =>
    value === null ? EMPTY : formatDate(value, { timeZone: "UTC" });
  const text = (value: string | null): React.ReactNode => (value === null || value === "" ? EMPTY : value);
  const defs = fields.data ?? [];
  const known = new Set(defs.map((def) => def.key));
  const strays = Object.keys(asset.custom_fields).filter((key) => !known.has(key));

  return (
    <div className="space-y-6">
      <dl className="divide-y divide-border rounded-xl border border-border bg-surface px-4">
        <Row label={t("assets.form.category")}>{text(asset.category_name)}</Row>
        <Row label={t("assets.form.model")}>{text(asset.model)}</Row>
        <Row label={t("assets.form.manufacturer")}>{text(asset.manufacturer_name)}</Row>
        <Row label={t("assets.form.supplier")}>{text(asset.supplier_name)}</Row>
        <Row label={t("assets.form.serial_number")}>{text(asset.serial_number)}</Row>
        <Row label={t("assets.form.owner_org_unit")}>{text(asset.owner_org_unit_name)}</Row>
        <Row label={t("assets.form.location")}>{text(asset.location_name)}</Row>
        <Row label={t("assets.columns.holder")}>
          <HolderCell holder={asset.holder} />
        </Row>
        {asset.parent !== null && (
          <Row label={t("assets.detail.parent")}>
            <Link
              to={`/assets/${asset.parent.id}`}
              className="text-primary underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
            >
              {asset.parent.name}
            </Link>
            <span className="ml-1 font-mono text-xs text-muted">{asset.parent.tag}</span>
          </Row>
        )}
        <Row label={t("assets.form.purchase_date")}>{date(asset.purchase_date)}</Row>
        <Row label={t("assets.form.purchase_cost")}>{text(asset.purchase_cost)}</Row>
        <Row label={t("assets.form.warranty_end")}>{date(asset.warranty_end)}</Row>
        <Row label={t("assets.form.notes")}>
          {asset.notes === null || asset.notes === "" ? (
            EMPTY
          ) : (
            <span className="whitespace-pre-wrap">{asset.notes}</span>
          )}
        </Row>
        <Row label={t("assets.detail.created")}>
          {asset.created_at === "" ? EMPTY : formatDateTime(asset.created_at)}
        </Row>
        <Row label={t("assets.detail.updated")}>
          {asset.updated_at === "" ? EMPTY : formatDateTime(asset.updated_at)}
        </Row>
      </dl>

      {(defs.length > 0 || strays.length > 0) && (
        <section aria-labelledby="asset-custom-heading" className="space-y-2">
          <h2 id="asset-custom-heading" className="text-base font-semibold">
            {t("assets.form.section_custom")}
          </h2>
          <dl className="divide-y divide-border rounded-xl border border-border bg-surface px-4">
            {defs.map((def) => {
              const entry = asset.encrypted_fields[def.key];
              return (
                <Row key={def.id} label={def.label}>
                  {def.is_encrypted ? (
                    entry === undefined ? (
                      EMPTY
                    ) : "is_set" in entry ? (
                      entry.is_set ? (
                        t("assets.detail.encrypted_set")
                      ) : (
                        t("assets.detail.encrypted_not_set")
                      )
                    ) : (
                      <CustomValue def={def} value={entry.value} formatDate={formatDate} />
                    )
                  ) : (
                    <CustomValue def={def} value={asset.custom_fields[def.key]} formatDate={formatDate} />
                  )}
                  {def.status === "archived" && (
                    <span className="ml-2 text-xs text-muted">{t("assets.detail.field_archived")}</span>
                  )}
                </Row>
              );
            })}
            {strays.map((key) => (
              <Row key={key} label={humanizeKey(key)}>
                {String(asset.custom_fields[key])}
              </Row>
            ))}
          </dl>
        </section>
      )}
    </div>
  );
};
