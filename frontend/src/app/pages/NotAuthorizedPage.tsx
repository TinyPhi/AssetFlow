// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { ShieldOff } from "lucide-react";
import type React from "react";
import { Link } from "react-router";
import { t } from "@/lib/i18n";

/** Shown by a guard when the member lacks the permission or module (P7-02b polishes it). */
export const NotAuthorizedPage: React.FC = () => (
  <section className="mx-auto flex max-w-md flex-col items-center gap-3 py-10 text-center">
    <ShieldOff aria-hidden="true" className="h-10 w-10 text-muted" />
    <h1 className="text-xl font-bold">{t("pages.not_authorized.title")}</h1>
    <p className="text-sm text-muted">{t("pages.not_authorized.body")}</p>
    <Link
      to="/"
      className="inline-flex min-h-11 items-center rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground"
    >
      {t("pages.not_authorized.back")}
    </Link>
  </section>
);
