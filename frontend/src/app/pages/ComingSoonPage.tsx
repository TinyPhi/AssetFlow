// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { t, type TranslationKey } from "@/lib/i18n";

/** A screen whose feature is not built yet: its title and a note. Each feature replaces its own. */
export const ComingSoonPage: React.FC<{ titleKey: TranslationKey }> = ({ titleKey }) => (
  <section className="space-y-2">
    <h1 className="text-2xl font-bold">{t(titleKey)}</h1>
    <p className="text-sm text-muted">{t("pages.coming_soon.title")}</p>
  </section>
);
