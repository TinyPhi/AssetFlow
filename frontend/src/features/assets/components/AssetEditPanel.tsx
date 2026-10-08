// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { useState } from "react";
import { useToast } from "@/app/toastContext";
import { t } from "@/lib/i18n";
import { useUpdateAsset } from "../hooks/useAssetDetail";
import { buildUpdateBody, hasChanges, serverFieldErrors } from "../lib/asset-form";
import { isVersionConflict, saveFailureMessage } from "../lib/failure";
import type { AssetDetail } from "../types";
import { AssetForm, type AssetFormSubmit } from "./AssetForm";

interface AssetEditPanelProps {
  asset: AssetDetail;
  onDone: () => void;
  /** The asset changed since it was read (a 409); the page offers a reload. */
  onConflict: () => void;
}

/** The edit form around one asset: sends only what changed, with the `version` it was read at. */
export const AssetEditPanel: React.FC<AssetEditPanelProps> = ({ asset, onDone, onConflict }) => {
  const { showToast } = useToast();
  const update = useUpdateAsset(asset.id);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);

  const submit = ({ core, initial, custom, moveComponents }: AssetFormSubmit): void => {
    if (initial === null) return;
    setFieldErrors({});
    setFormError(null);
    const body = buildUpdateBody(initial, core, custom, asset.version, moveComponents);
    if (!hasChanges(body)) {
      showToast(t("assets.form.no_changes"), "info");
      onDone();
      return;
    }
    update.mutate(body, {
      onSuccess: () => {
        showToast(t("assets.form.saved"), "success");
        onDone();
      },
      onError: (error) => {
        if (isVersionConflict(error)) {
          onConflict();
          return;
        }
        setFieldErrors(serverFieldErrors(error));
        setFormError(saveFailureMessage(error));
      },
    });
  };

  return (
    <AssetForm
      mode="edit"
      asset={asset}
      submitting={update.isPending}
      serverErrors={fieldErrors}
      formError={formError}
      onSubmit={submit}
      onCancel={onDone}
    />
  );
};
