// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { ShieldAlert } from "lucide-react";
import type React from "react";
import { Link } from "react-router";
import { t } from "@/lib/i18n";

export const NotAuthorizedPage: React.FC = () => (
  <section className="flex min-h-[50vh] flex-col items-center justify-center space-y-4 p-6 text-center">
    <div className="flex h-16 w-16 items-center justify-center rounded-full bg-danger/10 text-danger">
      <ShieldAlert className="h-10 w-10" aria-hidden="true" />
    </div>
    <h1 className="text-2xl font-bold tracking-tight text-foreground">{t("pages.not_authorized.title")}</h1>
    <p className="max-w-md text-sm text-muted">{t("pages.not_authorized.body")}</p>
    <div className="pt-2">
      <Link
        to="/"
        className="inline-flex min-h-11 items-center justify-center rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
      >
        {t("pages.not_authorized.back")}
      </Link>
    </div>
  </section>
);
