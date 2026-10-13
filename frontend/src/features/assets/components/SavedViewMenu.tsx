// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { Bookmark } from "lucide-react";
import type React from "react";
import { useState } from "react";
import { useToast } from "@/app/toastContext";
import { t } from "@/lib/i18n";
import {
  useCreateSavedView,
  useDeleteSavedView,
  useRenameSavedView,
  useSavedViews,
} from "../hooks/useSavedViews";
import { toViewQuery, type AssetListState } from "../lib/asset-filter-params";
import type { SavedView } from "../types";
import { BUTTON_CLASS, CONTROL_CLASS, PRIMARY_BUTTON_CLASS } from "./control-class";

interface SavedViewMenuProps {
  state: AssetListState;
  columns: readonly string[];
  onApply: (view: SavedView) => void;
}

/** Apply, save, rename and delete the member's own saved views. The panel sits in the page flow (no popover). */
export const SavedViewMenu: React.FC<SavedViewMenuProps> = ({ state, columns, onApply }) => {
  const { showToast } = useToast();
  const views = useSavedViews();
  const create = useCreateSavedView();
  const rename = useRenameSavedView();
  const remove = useDeleteSavedView();
  const [open, setOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [editing, setEditing] = useState<{ id: string; name: string } | null>(null);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);

  const fail = (): void => {
    showToast(t("assets.views.failed"), "danger");
  };

  return (
    <div className="contents">
      <button
        type="button"
        aria-expanded={open}
        aria-controls="saved-views-panel"
        onClick={() => {
          setOpen(!open);
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
        className={BUTTON_CLASS}
      >
        <Bookmark aria-hidden="true" className="h-4 w-4" />
        {t("assets.views.menu")}
      </button>
      {open && (
        <section
          id="saved-views-panel"
          aria-label={t("assets.views.menu")}
          className="order-last w-full space-y-4 rounded-xl border border-border bg-surface p-4"
        >
          <form
            className="flex flex-col gap-2 sm:flex-row"
            onSubmit={(event) => {
              event.preventDefault();
              const name = newName.trim();
              if (name === "") return;
              create.mutate(
                { name, query: toViewQuery(state.filters), sort: state.sort, columns: [...columns] },
                {
                  onSuccess: () => {
                    setNewName("");
                    showToast(t("assets.views.saved"), "success");
                  },
                  onError: fail,
                },
              );
            }}
          >
            <label className="sr-only" htmlFor="saved-view-name">
              {t("assets.views.name_label")}
            </label>
            <input
              id="saved-view-name"
              type="text"
              maxLength={100}
              value={newName}
              placeholder={t("assets.views.name_placeholder")}
              onChange={(event) => {
                setNewName(event.target.value);
              }}
              className={CONTROL_CLASS}
            />
            <button type="submit" disabled={create.isPending} className={PRIMARY_BUTTON_CLASS}>
              {t("assets.views.save_current")}
            </button>
          </form>

          {views.isPending && <p className="text-sm text-muted">{t("ui.state.loading")}</p>}
          {views.isError && <p className="text-sm text-danger">{t("assets.views.load_failed")}</p>}
          {views.data?.length === 0 && <p className="text-sm text-muted">{t("assets.views.none")}</p>}
          <ul className="space-y-2">
            {(views.data ?? []).map((view) => (
              <li key={view.id} className="flex flex-col gap-2 sm:flex-row sm:items-center">
                {editing?.id === view.id ? (
                  <form
                    className="flex flex-1 flex-col gap-2 sm:flex-row"
                    onSubmit={(event) => {
                      event.preventDefault();
                      const name = editing.name.trim();
                      if (name === "") return;
                      rename.mutate(
                        { view, name },
                        {
                          onSuccess: () => {
                            setEditing(null);
                            showToast(t("assets.views.renamed"), "success");
                          },
                          onError: fail,
                        },
                      );
                    }}
                  >
                    <label className="sr-only" htmlFor={`rename-${view.id}`}>
                      {t("assets.views.rename_label")}
                    </label>
                    <input
                      id={`rename-${view.id}`}
                      type="text"
                      maxLength={100}
                      value={editing.name}
                      onChange={(event) => {
                        setEditing({ id: view.id, name: event.target.value });
                      }}
                      className={CONTROL_CLASS}
                    />
                    <button type="submit" className={PRIMARY_BUTTON_CLASS}>
                      {t("assets.views.rename_save")}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setEditing(null);
                      }}
                      className={BUTTON_CLASS}
                    >
                      {t("assets.views.cancel")}
                    </button>
                  </form>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => {
                        onApply(view);
                        setOpen(false);
                      }}
                      className="min-h-11 flex-1 truncate rounded-lg px-3 text-left text-sm font-medium hover:bg-background focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
                    >
                      {view.name}
                    </button>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        aria-label={t("assets.views.rename_named", { name: view.name })}
                        onClick={() => {
                          setEditing({ id: view.id, name: view.name });
                        }}
                        className={BUTTON_CLASS}
                      >
                        {t("assets.views.rename")}
                      </button>
                      {confirmingId === view.id ? (
                        <button
                          type="button"
                          onClick={() => {
                            remove.mutate(view.id, {
                              onSuccess: () => {
                                setConfirmingId(null);
                                showToast(t("assets.views.deleted"), "success");
                              },
                              onError: fail,
                            });
                          }}
                          className={`${BUTTON_CLASS} text-danger`}
                        >
                          {t("assets.views.delete_confirm", { name: view.name })}
                        </button>
                      ) : (
                        <button
                          type="button"
                          aria-label={t("assets.views.delete_named", { name: view.name })}
                          onClick={() => {
                            setConfirmingId(view.id);
                          }}
                          className={BUTTON_CLASS}
                        >
                          {t("assets.views.delete")}
                        </button>
                      )}
                    </div>
                  </>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
};
