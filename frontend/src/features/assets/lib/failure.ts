// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { ProblemError } from "@/lib/api";
import { t } from "@/lib/i18n";

/** A write refused because the record changed since it was read (§C4.3). */
export function isVersionConflict(error: unknown): boolean {
  return error instanceof ProblemError && error.status === 409 && error.code.endsWith(".version_conflict");
}

/** The status change the template does not allow right now; the API's own message says why. */
export function isInvalidTransition(error: unknown): error is ProblemError {
  return error instanceof ProblemError && error.code === "asset.invalid_transition";
}

/** What went wrong with a save, in words; the API's `detail` is shown only where a screen asks for it. */
export function saveFailureMessage(error: unknown): string {
  if (error instanceof ProblemError) {
    if (error.status === 422) return t("assets.form.fix_errors");
    if (error.status === 403) return t("assets.form.denied");
    if (error.status === 404) return t("assets.form.gone");
    if (error.status === 409) return t("assets.form.conflict");
  }
  return t("assets.form.save_failed");
}
