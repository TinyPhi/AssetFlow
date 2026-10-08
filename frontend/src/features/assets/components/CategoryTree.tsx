// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { useMemo, useState } from "react";
import { useToast } from "@/app/toastContext";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { t } from "@/lib/i18n";
import { useCategoryMutations, useCategoryRecords } from "../hooks/useCatalog";
import { useVocabulary } from "../hooks/useAssetDetail";
import { humanizeKey } from "../lib/asset-filter-params";
import {
  categoryCreateBody,
  categoryErrors,
  categoryUpdateBody,
  categoryValues,
  catalogFailure,
  EMPTY_CATEGORY,
  moveTargets,
  type CategoryFormValues,
} from "../lib/catalog-form";
import { treeOrder } from "../lib/hierarchy";
import type { CategoryRecord } from "../types";
import { BUTTON_CLASS, CONTROL_CLASS, PRIMARY_BUTTON_CLASS } from "./control-class";
import { ConfirmDialog } from "./ConfirmDialog";
import { Dialog } from "./Dialog";
import { FormField } from "./FormField";

const NBSP = " ";

type Action =
  | { kind: "create" }
  | { kind: "edit"; category: CategoryRecord }
  | { kind: "move"; category: CategoryRecord }
  | { kind: "archive"; category: CategoryRecord };

interface CategoryTreeProps {
  selectedId: string;
  onSelect: (id: string) => void;
}

/** The category tree with create, rename (and its settings), move and archive; selecting one manages its fields. */
export const CategoryTree: React.FC<CategoryTreeProps> = ({ selectedId, onSelect }) => {
  const { showToast } = useToast();
  const [showArchived, setShowArchived] = useState(false);
  const categories = useCategoryRecords(showArchived ? "" : "active");
  const vocabulary = useVocabulary();
  const mutations = useCategoryMutations();
  const [action, setAction] = useState<Action | null>(null);
  const [values, setValues] = useState<CategoryFormValues>(EMPTY_CATEGORY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [failure, setFailure] = useState<string | null>(null);
  const [target, setTarget] = useState("");

  const rows = useMemo(() => treeOrder(categories.data ?? []), [categories.data]);
  const byId = useMemo(() => new Map((categories.data ?? []).map((c) => [c.id, c])), [categories.data]);

  const close = (): void => {
    setAction(null);
    setErrors({});
    setFailure(null);
  };
  const open = (next: Action): void => {
    setFailure(null);
    setErrors({});
    if (next.kind === "create") setValues(EMPTY_CATEGORY);
    if (next.kind === "edit") setValues(categoryValues(next.category));
    if (next.kind === "move") setTarget("");
    setAction(next);
  };
  const done = (message: string): void => {
    close();
    showToast(message, "success");
  };
  const fail = (error: Error): void => {
    setFailure(catalogFailure(error));
  };

  const submitForm = (): void => {
    if (action === null || (action.kind !== "create" && action.kind !== "edit")) return;
    const found = categoryErrors(values, action.kind);
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    if (action.kind === "create") {
      mutations.create.mutate(categoryCreateBody(values), {
        onSuccess: (created) => {
          onSelect(created.id);
          done(t("assets.categories.created"));
        },
        onError: fail,
      });
      return;
    }
    const body = categoryUpdateBody(categoryValues(action.category), values, action.category.version);
    mutations.update.mutate(
      { id: action.category.id, input: body },
      {
        onSuccess: () => {
          done(t("assets.categories.saved"));
        },
        onError: fail,
      },
    );
  };

  const levels = [...new Set([...(vocabulary.data?.criticality ?? []), values.default_criticality])].filter(
    (level) => level !== "",
  );

  let body: React.ReactNode;
  if (categories.isPending) body = <Skeleton rows={4} />;
  else if (categories.isError) {
    body = (
      <ErrorState
        message={t("assets.categories.load_failed")}
        onRetry={() => {
          void categories.refetch();
        }}
      />
    );
  } else if (rows.length === 0) {
    body = (
      <EmptyState
        title={t("assets.categories.empty_title")}
        message={t("assets.categories.empty_body")}
        action={{
          label: t("assets.categories.new"),
          onClick: () => {
            open({ kind: "create" });
          },
        }}
      />
    );
  } else {
    body = (
      <ul aria-label={t("assets.categories.tree_label")} className="space-y-2">
        {rows.map(({ node, depth }) => {
          const category = byId.get(node.id);
          if (category === undefined) return null;
          const archived = category.status === "archived";
          return (
            <li
              key={category.id}
              style={{ marginLeft: `${String(Math.min(depth, 6) * 0.75)}rem` }}
              className="rounded-xl border border-border bg-surface p-3"
            >
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <button
                    type="button"
                    aria-pressed={selectedId === category.id}
                    onClick={() => {
                      onSelect(category.id);
                    }}
                    className={`min-h-11 break-words text-left font-semibold underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus ${
                      selectedId === category.id ? "text-primary" : ""
                    }`}
                  >
                    {category.name}
                  </button>
                  <p className="text-xs text-muted">
                    <span className="font-mono">{category.code}</span>
                    {category.tag_prefix !== null &&
                      ` · ${t("assets.categories.prefix_value", { prefix: category.tag_prefix })}`}
                    {category.default_criticality !== null &&
                      ` · ${t("assets.detail.criticality_value", { level: humanizeKey(category.default_criticality) })}`}
                    {archived && ` · ${t("assets.categories.archived")}`}
                  </p>
                </div>
                {!archived && (
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      aria-label={t("assets.categories.edit_named", { name: category.name })}
                      onClick={() => {
                        open({ kind: "edit", category });
                      }}
                      className={BUTTON_CLASS}
                    >
                      {t("assets.categories.edit")}
                    </button>
                    <button
                      type="button"
                      aria-label={t("assets.categories.move_named", { name: category.name })}
                      onClick={() => {
                        open({ kind: "move", category });
                      }}
                      className={BUTTON_CLASS}
                    >
                      {t("assets.categories.move")}
                    </button>
                    <button
                      type="button"
                      aria-label={t("assets.categories.archive_named", { name: category.name })}
                      onClick={() => {
                        open({ kind: "archive", category });
                      }}
                      className={BUTTON_CLASS}
                    >
                      {t("assets.categories.archive")}
                    </button>
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    );
  }

  const text = (key: keyof CategoryFormValues, value: string): void => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };

  return (
    <section aria-labelledby="categories-heading" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="categories-heading" className="text-lg font-semibold">
          {t("assets.categories.title")}
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
            {t("assets.categories.new")}
          </button>
        </div>
      </div>
      {body}

      {(action?.kind === "create" || action?.kind === "edit") && (
        <Dialog
          title={action.kind === "create" ? t("assets.categories.new") : t("assets.categories.edit_title")}
          onClose={close}
        >
          <form
            noValidate
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              submitForm();
            }}
          >
            {action.kind === "create" && (
              <FormField
                label={t("assets.categories.code")}
                required
                error={errors["code"]}
                hint={t("assets.categories.code_hint")}
              >
                {(control) => (
                  <input
                    {...control}
                    type="text"
                    value={values.code}
                    maxLength={64}
                    onChange={(event) => {
                      text("code", event.target.value);
                    }}
                    className={CONTROL_CLASS}
                  />
                )}
              </FormField>
            )}
            <FormField label={t("assets.form.name")} required error={errors["name"]}>
              {(control) => (
                <input
                  {...control}
                  type="text"
                  value={values.name}
                  maxLength={255}
                  onChange={(event) => {
                    text("name", event.target.value);
                  }}
                  className={CONTROL_CLASS}
                />
              )}
            </FormField>
            {action.kind === "create" && (
              <FormField label={t("assets.categories.parent")}>
                {(control) => (
                  <select
                    {...control}
                    value={values.parent_id}
                    onChange={(event) => {
                      text("parent_id", event.target.value);
                    }}
                    className={CONTROL_CLASS}
                  >
                    <option value="">{t("assets.categories.no_parent")}</option>
                    {rows
                      .filter(({ node }) => byId.get(node.id)?.status === "active")
                      .map(({ node, depth }) => (
                        <option key={node.id} value={node.id}>
                          {NBSP.repeat(depth * 3)}
                          {node.name}
                        </option>
                      ))}
                  </select>
                )}
              </FormField>
            )}
            <FormField
              label={t("assets.categories.tag_prefix")}
              error={errors["tag_prefix"]}
              hint={t("assets.categories.tag_prefix_hint")}
            >
              {(control) => (
                <input
                  {...control}
                  type="text"
                  value={values.tag_prefix}
                  maxLength={10}
                  onChange={(event) => {
                    text("tag_prefix", event.target.value);
                  }}
                  className={CONTROL_CLASS}
                />
              )}
            </FormField>
            <FormField label={t("assets.categories.default_criticality")}>
              {(control) => (
                <select
                  {...control}
                  value={values.default_criticality}
                  onChange={(event) => {
                    text("default_criticality", event.target.value);
                  }}
                  className={CONTROL_CLASS}
                >
                  <option value="">{t("assets.form.none_chosen")}</option>
                  {levels.map((level) => (
                    <option key={level} value={level}>
                      {humanizeKey(level)}
                    </option>
                  ))}
                </select>
              )}
            </FormField>
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
                {action.kind === "create" ? t("assets.categories.create") : t("assets.form.save_changes")}
              </button>
            </div>
          </form>
        </Dialog>
      )}

      {action?.kind === "move" && (
        <Dialog title={t("assets.categories.move_title", { name: action.category.name })} onClose={close}>
          <form
            noValidate
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (target === "") return;
              mutations.move.mutate(
                { id: action.category.id, parentId: target, version: action.category.version },
                {
                  onSuccess: () => {
                    done(t("assets.categories.moved"));
                  },
                  onError: fail,
                },
              );
            }}
          >
            <FormField label={t("assets.categories.new_parent")} required>
              {(control) => (
                <select
                  {...control}
                  value={target}
                  onChange={(event) => {
                    setTarget(event.target.value);
                  }}
                  className={CONTROL_CLASS}
                >
                  <option value="">{t("assets.categories.choose_parent")}</option>
                  {treeOrder(moveTargets(categories.data ?? [], action.category)).map(({ node, depth }) => (
                    <option key={node.id} value={node.id}>
                      {NBSP.repeat(depth * 3)}
                      {node.name}
                    </option>
                  ))}
                </select>
              )}
            </FormField>
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
                disabled={target === "" || mutations.move.isPending}
                className={PRIMARY_BUTTON_CLASS}
              >
                {t("assets.categories.move")}
              </button>
            </div>
          </form>
        </Dialog>
      )}

      {action?.kind === "archive" && (
        <ConfirmDialog
          title={t("assets.categories.archive_title", { name: action.category.name })}
          body={t("assets.categories.archive_body")}
          confirmLabel={t("assets.categories.archive")}
          pending={mutations.archive.isPending}
          error={failure}
          onClose={close}
          onConfirm={() => {
            mutations.archive.mutate(
              { id: action.category.id, version: action.category.version },
              {
                onSuccess: () => {
                  if (selectedId === action.category.id) onSelect("");
                  done(t("assets.categories.archived_done"));
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
