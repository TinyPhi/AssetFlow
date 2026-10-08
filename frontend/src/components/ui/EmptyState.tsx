// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { Inbox } from "lucide-react";
import type React from "react";
import { t } from "@/lib/i18n";

interface EmptyStateProps {
  title?: string;
  message?: string;
  /** The one thing the member can do about it (for example "Add a team"); omitted when they cannot. */
  action?: { label: string; onClick: () => void };
}

/** The empty state of a list (§C4.9): say so, and offer the next step when there is one. */
export const EmptyState: React.FC<EmptyStateProps> = ({ title, message, action }) => (
  <div className="flex flex-col items-center gap-3 rounded-xl border border-border p-8 text-center">
    <Inbox aria-hidden="true" className="h-8 w-8 text-muted" />
    <p className="font-semibold text-foreground">{title ?? t("ui.empty.title")}</p>
    {message !== undefined && <p className="text-sm text-muted">{message}</p>}
    {action !== undefined && (
      <button
        type="button"
        onClick={action.onClick}
        className="min-h-11 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
      >
        {action.label}
      </button>
    )}
  </div>
);
