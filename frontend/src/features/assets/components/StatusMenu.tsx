// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { useState } from "react";
import { ProblemError } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useChangeStatus, useTransitions } from "../hooks/useAssetDetail";
import { isInvalidTransition, isVersionConflict } from "../lib/failure";
import type { Transition } from "../types";
import { BUTTON_CLASS, CONTROL_CLASS, PRIMARY_BUTTON_CLASS } from "./control-class";
import { Dialog } from "./Dialog";
import { FormField } from "./FormField";

interface StatusMenuProps {
  assetId: string;
  version: number;
  /** The asset changed under us (a 409): the page offers a reload. */
  onConflict: () => void;
}

/**
 * The status changes the API lists for this asset now (`GET /transitions`); nothing else is offered. A change
 * that needs a reason asks for it; a refusal shows the API's own message.
 */
export const StatusMenu: React.FC<StatusMenuProps> = ({ assetId, version, onConflict }) => {
  const transitions = useTransitions(assetId, version);
  const change = useChangeStatus(assetId);
  const [chosen, setChosen] = useState<Transition | null>(null);
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState<string | null>(null);
  const [refusal, setRefusal] = useState<string | null>(null);

  const items = transitions.data ?? [];
  if (transitions.isPending) return null;
  if (transitions.isError || items.length === 0) {
    return transitions.isError ? (
      <p role="alert" className="text-sm text-danger">
        {t("assets.detail.transitions_failed")}
      </p>
    ) : (
      <p className="text-sm text-muted">{t("assets.detail.no_transitions")}</p>
    );
  }

  const close = (): void => {
    setChosen(null);
    setReason("");
    setReasonError(null);
    setRefusal(null);
    change.reset();
  };

  const apply = (transition: Transition, text: string): void => {
    change.mutate(
      { to_status: transition.to_status, version, ...(text.trim() === "" ? {} : { reason: text.trim() }) },
      {
        onSuccess: close,
        onError: (error) => {
          if (isVersionConflict(error)) {
            close();
            onConflict();
          } else if (isInvalidTransition(error)) {
            setRefusal(error.detail === "" ? t("assets.detail.transition_refused") : error.detail);
          } else if (error instanceof ProblemError && error.status === 403) {
            setRefusal(t("assets.form.denied"));
          } else {
            setRefusal(t("assets.detail.status_failed"));
          }
        },
      },
    );
  };

  return (
    <div>
      <ul aria-label={t("assets.detail.status_actions")} className="flex flex-wrap gap-2">
        {items.map((transition) => (
          <li key={transition.to_status}>
            <button
              type="button"
              onClick={() => {
                setRefusal(null);
                if (transition.requires_reason) setChosen(transition);
                else {
                  setChosen(transition);
                  apply(transition, "");
                }
              }}
              className={BUTTON_CLASS}
            >
              {t("assets.detail.move_to", { status: transition.to_label })}
            </button>
          </li>
        ))}
      </ul>
      {refusal !== null && chosen !== null && !chosen.requires_reason && (
        <Dialog title={t("assets.detail.transition_refused_title")} role="alertdialog" onClose={close}>
          <p className="text-sm">{refusal}</p>
        </Dialog>
      )}
      {chosen?.requires_reason === true && (
        <Dialog title={t("assets.detail.reason_title", { status: chosen.to_label })} onClose={close}>
          <form
            noValidate
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (reason.trim() === "") {
                setReasonError(t("assets.detail.reason_required"));
                return;
              }
              setReasonError(null);
              apply(chosen, reason);
            }}
          >
            <FormField label={t("assets.detail.reason_label")} required error={reasonError ?? undefined}>
              {(control) => (
                <textarea
                  {...control}
                  value={reason}
                  maxLength={2000}
                  onChange={(event) => {
                    setReason(event.target.value);
                  }}
                  className={`${CONTROL_CLASS} h-auto min-h-24 py-2`}
                />
              )}
            </FormField>
            {refusal !== null && (
              <p role="alert" className="text-sm text-danger">
                {refusal}
              </p>
            )}
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" onClick={close} className={BUTTON_CLASS}>
                {t("assets.form.cancel")}
              </button>
              <button type="submit" disabled={change.isPending} className={PRIMARY_BUTTON_CLASS}>
                {t("assets.detail.confirm_status")}
              </button>
            </div>
          </form>
        </Dialog>
      )}
    </div>
  );
};
