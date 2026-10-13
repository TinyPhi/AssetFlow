// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { AlertCircle } from "lucide-react";
import type React from "react";
import { t } from "@/lib/i18n";

interface ErrorStateProps {
  /** Text under the title; the caller supplies a translated message (never a raw server message). */
  message?: string;
  onRetry?: () => void;
}

/** The error state of a list or page (§C4.9): what failed and a way to try again. */
export const ErrorState: React.FC<ErrorStateProps> = ({ message, onRetry }) => (
  <div
    role="alert"
    className="flex flex-col items-center gap-3 rounded-xl border border-danger p-6 text-center"
  >
    <AlertCircle aria-hidden="true" className="h-8 w-8 text-danger" />
    <p className="font-semibold text-foreground">{t("ui.error.title")}</p>
    {message !== undefined && <p className="text-sm text-muted">{message}</p>}
    {onRetry !== undefined && (
      <button
        type="button"
        onClick={onRetry}
        className="min-h-11 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
      >
        {t("ui.error.retry")}
      </button>
    )}
  </div>
);
