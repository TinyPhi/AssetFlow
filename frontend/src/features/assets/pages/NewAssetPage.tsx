// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { ArrowLeft } from "lucide-react";
import type React from "react";
import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import { useToast } from "@/app/toastContext";
import { ProblemError, newIdempotencyKey } from "@/lib/api";
import { t } from "@/lib/i18n";
import { AssetForm, type AssetFormSubmit } from "../components/AssetForm";
import { useCreateAsset } from "../hooks/useAssetDetail";
import { buildCreateBody, serverFieldErrors } from "../lib/asset-form";
import { saveFailureMessage } from "../lib/failure";

/** `/assets/new` (UF3): a new asset with the category's custom fields; the generated tag is shown on success. */
export const NewAssetPage: React.FC = () => {
  const navigate = useNavigate();
  const { showToast } = useToast();
  const create = useCreateAsset();
  // One key per logical create: a retry of the same request reuses it, a corrected request gets a new one.
  const key = useRef(newIdempotencyKey());
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);

  const submit = ({ core, custom }: AssetFormSubmit): void => {
    setFieldErrors({});
    setFormError(null);
    create.mutate(
      { body: buildCreateBody(core, custom), idempotencyKey: key.current },
      {
        onSuccess: (asset) => {
          showToast(t("assets.form.created", { tag: asset.tag }), "success");
          void navigate(`/assets/${asset.id}`);
        },
        onError: (error) => {
          if (error instanceof ProblemError && error.status < 500) key.current = newIdempotencyKey();
          setFieldErrors(serverFieldErrors(error));
          setFormError(saveFailureMessage(error));
        },
      },
    );
  };

  return (
    <section className="space-y-4">
      <Link
        to="/assets"
        className="inline-flex min-h-11 items-center gap-1 text-sm text-primary hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
      >
        <ArrowLeft aria-hidden="true" className="h-4 w-4" />
        {t("assets.form.back_to_list")}
      </Link>
      <h1 className="text-2xl font-bold tracking-tight">{t("assets.form.new_title")}</h1>
      <div className="rounded-xl border border-border bg-surface p-4 md:p-6">
        <AssetForm
          mode="create"
          submitting={create.isPending}
          serverErrors={fieldErrors}
          formError={formError}
          onSubmit={submit}
          onCancel={() => {
            void navigate("/assets");
          }}
        />
      </div>
    </section>
  );
};
