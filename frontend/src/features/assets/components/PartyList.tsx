// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { useState } from "react";
import { useToast } from "@/app/toastContext";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { t } from "@/lib/i18n";
import { useParties, usePartyMutations } from "../hooks/useCatalog";
import { catalogFailure, EMPTY_PARTY, partyErrors, type PartyFormValues } from "../lib/catalog-form";
import type { PartyKind, PartyRecord } from "../types";
import { BUTTON_CLASS, CONTROL_CLASS, PRIMARY_BUTTON_CLASS } from "./control-class";
import { ConfirmDialog } from "./ConfirmDialog";
import { Dialog } from "./Dialog";
import { FormField } from "./FormField";

type Action =
  { kind: "create" } | { kind: "edit"; party: PartyRecord } | { kind: "archive"; party: PartyRecord };

/** Manufacturers or suppliers (one shape): list, create, edit and archive. */
export const PartyList: React.FC<{ kind: PartyKind }> = ({ kind }) => {
  const manufacturers = kind === "manufacturers";
  const { showToast } = useToast();
  const [showArchived, setShowArchived] = useState(false);
  const parties = useParties(kind, showArchived ? "" : "active");
  const mutations = usePartyMutations(kind);
  const [action, setAction] = useState<Action | null>(null);
  const [values, setValues] = useState<PartyFormValues>(EMPTY_PARTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [failure, setFailure] = useState<string | null>(null);

  const heading = manufacturers ? t("assets.categories.manufacturers") : t("assets.categories.suppliers");
  const headingId = `${kind}-heading`;

  const close = (): void => {
    setAction(null);
    setErrors({});
    setFailure(null);
  };
  const open = (next: Action): void => {
    setErrors({});
    setFailure(null);
    setValues(
      next.kind === "edit"
        ? { code: next.party.code ?? "", name: next.party.name, notes: next.party.notes ?? "" }
        : EMPTY_PARTY,
    );
    setAction(next);
  };
  const done = (message: string): void => {
    close();
    showToast(message, "success");
  };
  const fail = (error: Error): void => {
    setFailure(catalogFailure(error));
  };

  const submit = (): void => {
    if (action === null || action.kind === "archive") return;
    const found = partyErrors(values, action.kind);
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    if (action.kind === "create") {
      mutations.create.mutate(
        {
          name: values.name.trim(),
          ...(values.code.trim() === "" ? {} : { code: values.code.trim() }),
          ...(values.notes.trim() === "" ? {} : { notes: values.notes.trim() }),
        },
        {
          onSuccess: () => {
            done(t("assets.categories.party_created"));
          },
          onError: fail,
        },
      );
      return;
    }
    const { party } = action;
    const input: Record<string, unknown> & { version: number } = { version: party.version };
    if (values.name.trim() !== party.name) input["name"] = values.name.trim();
    if (values.notes.trim() !== (party.notes ?? "")) {
      if (values.notes.trim() === "") input["clear_notes"] = true;
      else input["notes"] = values.notes.trim();
    }
    mutations.update.mutate(
      { id: party.id, input },
      {
        onSuccess: () => {
          done(t("assets.categories.party_saved"));
        },
        onError: fail,
      },
    );
  };

  let body: React.ReactNode;
  if (parties.isPending) body = <Skeleton rows={2} />;
  else if (parties.isError) {
    body = (
      <ErrorState
        message={t("assets.categories.party_load_failed")}
        onRetry={() => {
          void parties.refetch();
        }}
      />
    );
  } else if (parties.data.length === 0) {
    body = <EmptyState title={t("assets.categories.party_empty")} />;
  } else {
    body = (
      <ul aria-label={heading} className="space-y-2">
        {parties.data.map((party) => (
          <li
            key={party.id}
            className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-3 sm:flex-row sm:items-center sm:justify-between"
          >
            <div className="min-w-0">
              <p className="break-words font-semibold">{party.name}</p>
              <p className="text-xs text-muted">
                {party.code !== null && <span className="font-mono">{party.code}</span>}
                {party.status === "archived" &&
                  `${party.code === null ? "" : " · "}${t("assets.categories.archived")}`}
              </p>
            </div>
            {party.status !== "archived" && (
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  aria-label={t("assets.categories.edit_named", { name: party.name })}
                  onClick={() => {
                    open({ kind: "edit", party });
                  }}
                  className={BUTTON_CLASS}
                >
                  {t("assets.categories.edit")}
                </button>
                <button
                  type="button"
                  aria-label={t("assets.categories.archive_named", { name: party.name })}
                  onClick={() => {
                    open({ kind: "archive", party });
                  }}
                  className={BUTTON_CLASS}
                >
                  {t("assets.categories.archive")}
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
    );
  }

  return (
    <section aria-labelledby={headingId} className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id={headingId} className="text-lg font-semibold">
          {heading}
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
            {manufacturers ? t("assets.categories.manufacturer_new") : t("assets.categories.supplier_new")}
          </button>
        </div>
      </div>
      {body}

      {(action?.kind === "create" || action?.kind === "edit") && (
        <Dialog
          title={
            action.kind === "create"
              ? manufacturers
                ? t("assets.categories.manufacturer_new")
                : t("assets.categories.supplier_new")
              : t("assets.categories.party_edit_title")
          }
          onClose={close}
        >
          <form
            noValidate
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              submit();
            }}
          >
            <FormField label={t("assets.form.name")} required error={errors["name"]}>
              {(control) => (
                <input
                  {...control}
                  type="text"
                  value={values.name}
                  maxLength={255}
                  onChange={(event) => {
                    setValues((prev) => ({ ...prev, name: event.target.value }));
                  }}
                  className={CONTROL_CLASS}
                />
              )}
            </FormField>
            {action.kind === "create" && (
              <FormField
                label={t("assets.categories.code")}
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
                      setValues((prev) => ({ ...prev, code: event.target.value }));
                    }}
                    className={CONTROL_CLASS}
                  />
                )}
              </FormField>
            )}
            <FormField label={t("assets.form.notes")}>
              {(control) => (
                <textarea
                  {...control}
                  value={values.notes}
                  onChange={(event) => {
                    setValues((prev) => ({ ...prev, notes: event.target.value }));
                  }}
                  className={`${CONTROL_CLASS} h-auto min-h-24 py-2`}
                />
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

      {action?.kind === "archive" && (
        <ConfirmDialog
          title={t("assets.categories.party_archive_title", { name: action.party.name })}
          body={t("assets.categories.party_archive_body")}
          confirmLabel={t("assets.categories.archive")}
          pending={mutations.archive.isPending}
          error={failure}
          onClose={close}
          onConfirm={() => {
            mutations.archive.mutate(
              { id: action.party.id, version: action.party.version },
              {
                onSuccess: () => {
                  done(t("assets.categories.party_archived_done"));
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
