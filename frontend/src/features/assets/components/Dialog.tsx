// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { useEffect, useId, useRef } from "react";
import { t } from "@/lib/i18n";
import { BUTTON_CLASS } from "./control-class";

interface DialogProps {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  /** `alertdialog` for a refusal or a conflict that needs an answer. */
  role?: "dialog" | "alertdialog";
}

/**
 * A modal dialog: full screen on a phone, a centred card from 640 px up. Focus moves into it when it opens and
 * back to the control that opened it when it closes; Escape closes it.
 */
export const Dialog: React.FC<DialogProps> = ({ title, onClose, children, role = "dialog" }) => {
  const titleId = useId();
  const panel = useRef<HTMLDivElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  // Escape closes the dialog wherever the focus is inside it.
  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onCloseRef.current();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const first = panel.current?.querySelector<HTMLElement>(
      "input:not([type=hidden]), select, textarea, button:not([data-dialog-close])",
    );
    (first ?? panel.current)?.focus();
    return () => {
      opener?.focus();
    };
  }, []);

  return (
    <div className="fixed inset-0 z-40 flex items-stretch justify-center bg-foreground/40 sm:items-center sm:p-4">
      <div
        ref={panel}
        role={role}
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="flex h-full w-full flex-col overflow-y-auto bg-surface p-4 text-foreground sm:h-auto sm:max-h-full sm:max-w-lg sm:rounded-xl sm:border sm:border-border sm:p-6"
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <h2 id={titleId} className="text-lg font-semibold">
            {title}
          </h2>
          <button type="button" data-dialog-close="" onClick={onClose} className={BUTTON_CLASS}>
            {t("assets.dialog.close")}
          </button>
        </div>
        {children}
      </div>
    </div>
  );
};
