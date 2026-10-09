// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { useState } from "react";
import { Link } from "react-router";
import { useToast } from "@/app/toastContext";
import { ProblemError } from "@/lib/api";
import { t, useFormat } from "@/lib/i18n";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui";
import {
  useAssetSearch,
  useAttachComponent,
  useComponents,
  useDetachComponent,
  useVocabulary,
} from "../hooks/useAssetDetail";
import { isVersionConflict } from "../lib/failure";
import { statusLabel } from "../lib/status-label";
import type { ComponentChild } from "../types";
import { BUTTON_CLASS, CONTROL_CLASS, PRIMARY_BUTTON_CLASS } from "./control-class";
import { Dialog } from "./Dialog";
import { FormField } from "./FormField";

interface ComponentsPanelProps {
  assetId: string;
  version: number;
  canEdit: boolean;
  onConflict: () => void;
}

/** The asset's current components: attach one (search by name or tag) and detach with a confirmation. */
export const ComponentsPanel: React.FC<ComponentsPanelProps> = ({
  assetId,
  version,
  canEdit,
  onConflict,
}) => {
  const components = useComponents(assetId);
  const vocabulary = useVocabulary();
  const { formatDate } = useFormat();
  const { showToast } = useToast();
  const attach = useAttachComponent(assetId);
  const detach = useDetachComponent(assetId);
  const [attaching, setAttaching] = useState(false);
  const [search, setSearch] = useState("");
  const [detaching, setDetaching] = useState<ComponentChild | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const results = useAssetSearch(search);

  const current = (components.data ?? []).filter((child) => child.detached_at === null);
  const attachedIds = new Set([assetId, ...current.map((child) => child.child_asset_id)]);

  const fail = (error: Error): void => {
    if (isVersionConflict(error)) {
      setAttaching(false);
      setDetaching(null);
      onConflict();
      return;
    }
    setProblem(
      error instanceof ProblemError && error.detail !== ""
        ? error.detail
        : t("assets.detail.components_failed"),
    );
  };

  const closeAttach = (): void => {
    setAttaching(false);
    setSearch("");
    setProblem(null);
  };

  if (components.isPending) return <Skeleton rows={3} />;
  if (components.isError) {
    return (
      <ErrorState
        message={t("assets.detail.components_load_failed")}
        onRetry={() => {
          void components.refetch();
        }}
      />
    );
  }

  return (
    <div className="space-y-4">
      {canEdit && (
        <button
          type="button"
          onClick={() => {
            setProblem(null);
            setAttaching(true);
          }}
          className={PRIMARY_BUTTON_CLASS}
        >
          {t("assets.detail.attach")}
        </button>
      )}
      {current.length === 0 ? (
        <EmptyState title={t("assets.detail.no_components")} />
      ) : (
        <ul aria-label={t("assets.detail.components_list")} className="space-y-2">
          {current.map((child) => (
            <li
              key={child.component_id}
              className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-3 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="min-w-0">
                <Link
                  to={`/assets/${child.child_asset_id}`}
                  className="font-semibold text-primary underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
                >
                  {child.name}
                </Link>
                <p className="text-xs text-muted">
                  <span className="font-mono">{child.tag}</span>
                  {" · "}
                  {statusLabel(vocabulary.data, child.status)}
                  {child.attached_at !== "" &&
                    ` · ${t("assets.detail.attached_on", { date: formatDate(child.attached_at) })}`}
                </p>
              </div>
              {canEdit && (
                <button
                  type="button"
                  aria-label={t("assets.detail.detach_named", { name: child.name })}
                  onClick={() => {
                    setProblem(null);
                    setDetaching(child);
                  }}
                  className={BUTTON_CLASS}
                >
                  {t("assets.detail.detach")}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {attaching && (
        <Dialog title={t("assets.detail.attach_title")} onClose={closeAttach}>
          <div className="space-y-4">
            <FormField label={t("assets.detail.attach_search")} hint={t("assets.detail.attach_hint")}>
              {(control) => (
                <input
                  {...control}
                  type="search"
                  value={search}
                  onChange={(event) => {
                    setSearch(event.target.value);
                  }}
                  className={CONTROL_CLASS}
                />
              )}
            </FormField>
            {results.isPending && search.trim().length >= 2 && (
              <p className="text-sm text-muted">{t("ui.state.loading")}</p>
            )}
            {results.data?.length === 0 && (
              <p className="text-sm text-muted">{t("assets.detail.attach_none")}</p>
            )}
            <ul aria-label={t("assets.detail.attach_results")} className="space-y-2">
              {(results.data ?? [])
                .filter((item) => !attachedIds.has(item.id))
                .map((item) => (
                  <li key={item.id}>
                    <button
                      type="button"
                      disabled={attach.isPending}
                      onClick={() => {
                        attach.mutate(
                          { childId: item.id, version },
                          {
                            onSuccess: () => {
                              closeAttach();
                              showToast(t("assets.detail.attached", { name: item.name }), "success");
                            },
                            onError: fail,
                          },
                        );
                      }}
                      className={`${BUTTON_CLASS} w-full justify-between text-left`}
                    >
                      <span className="min-w-0 break-words">{item.name}</span>
                      <span className="font-mono text-xs text-muted">{item.tag}</span>
                    </button>
                  </li>
                ))}
            </ul>
            {problem !== null && (
              <p role="alert" className="text-sm text-danger">
                {problem}
              </p>
            )}
          </div>
        </Dialog>
      )}

      {detaching !== null && (
        <Dialog
          title={t("assets.detail.detach_title", { name: detaching.name })}
          role="alertdialog"
          onClose={() => {
            setDetaching(null);
          }}
        >
          <p className="mb-4 text-sm">{t("assets.detail.detach_body")}</p>
          {problem !== null && (
            <p role="alert" className="mb-4 text-sm text-danger">
              {problem}
            </p>
          )}
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button
              type="button"
              onClick={() => {
                setDetaching(null);
              }}
              className={BUTTON_CLASS}
            >
              {t("assets.form.cancel")}
            </button>
            <button
              type="button"
              disabled={detach.isPending}
              onClick={() => {
                detach.mutate(
                  { childId: detaching.child_asset_id, version },
                  {
                    onSuccess: () => {
                      setDetaching(null);
                      showToast(t("assets.detail.detached", { name: detaching.name }), "success");
                    },
                    onError: fail,
                  },
                );
              }}
              className={PRIMARY_BUTTON_CLASS}
            >
              {t("assets.detail.detach_confirm")}
            </button>
          </div>
        </Dialog>
      )}
    </div>
  );
};
