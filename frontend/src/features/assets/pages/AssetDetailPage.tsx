// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { ArrowLeft, Pencil } from "lucide-react";
import type React from "react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { ProblemError } from "@/lib/api";
import { t } from "@/lib/i18n";
import { usePermission } from "@/lib/permissions";
import { AssetDetails } from "../components/AssetDetails";
import { AssetEditPanel } from "../components/AssetEditPanel";
import { StatusPill } from "../components/AssetCells";
import { BUTTON_CLASS, PRIMARY_BUTTON_CLASS } from "../components/control-class";
import { ComponentsPanel } from "../components/ComponentsPanel";
import { Dialog } from "../components/Dialog";
import { DetailTabs, type DetailTab } from "../components/DetailTabs";
import { StatusMenu } from "../components/StatusMenu";
import { useAsset, useVocabulary } from "../hooks/useAssetDetail";
import { humanizeKey } from "../lib/asset-filter-params";
import { statusLabel } from "../lib/status-label";

/** `/assets/:id` (§B4.8.3): the asset, its status moves, its components, and an edit mode on the same form. */
export const AssetDetailPage: React.FC = () => {
  const { id = "" } = useParams();
  const asset = useAsset(id);
  const vocabulary = useVocabulary();
  const [tab, setTab] = useState<DetailTab>("details");
  const [editing, setEditing] = useState(false);
  const [conflict, setConflict] = useState(false);
  const data = asset.data;
  const canUpdate = usePermission(
    "asset.update",
    data === undefined ? undefined : { orgUnitId: data.owner_org_unit_id },
  );

  const back = (
    <Link
      to="/assets"
      className="inline-flex min-h-11 items-center gap-1 text-sm text-primary hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
    >
      <ArrowLeft aria-hidden="true" className="h-4 w-4" />
      {t("assets.form.back_to_list")}
    </Link>
  );

  if (asset.isPending) return <Skeleton rows={6} />;
  if (asset.isError || data === undefined) {
    const missing = asset.error instanceof ProblemError && asset.error.status === 404;
    return (
      <section className="space-y-4">
        {back}
        {missing ? (
          <EmptyState
            title={t("assets.detail.not_found_title")}
            message={t("assets.detail.not_found_body")}
          />
        ) : (
          <ErrorState
            message={t("assets.detail.load_failed")}
            onRetry={() => {
              void asset.refetch();
            }}
          />
        )}
      </section>
    );
  }

  const reload = (): void => {
    setConflict(false);
    setEditing(false);
    void asset.refetch();
  };

  const showConflict = (): void => {
    setConflict(true);
  };

  return (
    <section className="space-y-4">
      {back}
      <header className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="font-mono text-sm text-muted">{data.tag}</p>
            <h1 className="break-words text-2xl font-bold tracking-tight">{data.name}</h1>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <StatusPill status={data.status} label={statusLabel(vocabulary.data, data.status)} />
              {data.criticality !== null && (
                <span className="text-sm text-muted">
                  {t("assets.detail.criticality_value", { level: humanizeKey(data.criticality) })}
                </span>
              )}
            </div>
          </div>
          {canUpdate && !editing && (
            <button
              type="button"
              onClick={() => {
                setEditing(true);
              }}
              className={PRIMARY_BUTTON_CLASS}
            >
              <Pencil aria-hidden="true" className="h-4 w-4" />
              {t("assets.detail.edit")}
            </button>
          )}
        </div>
        {canUpdate && !editing && (
          <StatusMenu assetId={data.id} version={data.version} onConflict={showConflict} />
        )}
      </header>

      {editing ? (
        <div className="rounded-xl border border-border bg-surface p-4 md:p-6">
          <AssetEditPanel
            asset={data}
            onDone={() => {
              setEditing(false);
            }}
            onConflict={showConflict}
          />
        </div>
      ) : (
        <>
          <DetailTabs value={tab} onChange={setTab} />
          <div id="asset-tab-panel" role="tabpanel" aria-labelledby={`asset-tab-${tab}`} className="pt-2">
            {tab === "details" && <AssetDetails asset={data} />}
            {tab === "components" && (
              <ComponentsPanel
                assetId={data.id}
                version={data.version}
                canEdit={canUpdate}
                onConflict={showConflict}
              />
            )}
            {tab === "custody" && <EmptyState title={t("assets.detail.custody_soon")} />}
            {tab === "history" && <EmptyState title={t("assets.detail.history_soon")} />}
          </div>
        </>
      )}

      {conflict && (
        <Dialog title={t("assets.detail.conflict_title")} role="alertdialog" onClose={reload}>
          <p className="mb-4 text-sm">{t("assets.detail.conflict_body")}</p>
          <div className="flex justify-end">
            <button type="button" onClick={reload} className={BUTTON_CLASS}>
              {t("assets.detail.conflict_reload")}
            </button>
          </div>
        </Dialog>
      )}
    </section>
  );
};
