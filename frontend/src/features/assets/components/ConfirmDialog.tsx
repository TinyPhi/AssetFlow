// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { t } from "@/lib/i18n";
import { BUTTON_CLASS, PRIMARY_BUTTON_CLASS } from "./control-class";
import { Dialog } from "./Dialog";

interface ConfirmDialogProps {
  title: string;
  body: string;
  confirmLabel: string;
  pending: boolean;
  /** The API's refusal, shown in the dialog (for example the blocker that stops an archive). */
  error: string | null;
  onConfirm: () => void;
  onClose: () => void;
}

/** A yes/no question before a change that is hard to undo; a refusal stays in the dialog with its reason. */
export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  title,
  body,
  confirmLabel,
  pending,
  error,
  onConfirm,
  onClose,
}) => (
  <Dialog title={title} role="alertdialog" onClose={onClose}>
    <p className="mb-4 text-sm">{body}</p>
    {error !== null && (
      <p role="alert" className="mb-4 rounded-lg border border-danger p-3 text-sm text-danger">
        {error}
      </p>
    )}
    <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
      <button type="button" onClick={onClose} className={BUTTON_CLASS}>
        {t("assets.form.cancel")}
      </button>
      <button type="button" disabled={pending} onClick={onConfirm} className={PRIMARY_BUTTON_CLASS}>
        {confirmLabel}
      </button>
    </div>
  </Dialog>
);
