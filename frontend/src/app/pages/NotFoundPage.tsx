// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { t } from "@/lib/i18n";

export const NotFoundPage: React.FC = () => (
  <section className="mx-auto max-w-md py-10 text-center">
    <h1 className="text-xl font-bold">{t("pages.not_found.title")}</h1>
    <p className="mt-2 text-sm text-muted">{t("pages.not_found.body")}</p>
  </section>
);
