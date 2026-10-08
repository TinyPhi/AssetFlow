// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { useState } from "react";
import { t } from "@/lib/i18n";
import { CategoryTree } from "../components/CategoryTree";
import { CustomFieldsPanel } from "../components/CustomFieldsPanel";
import { PartyList } from "../components/PartyList";
import { useCategoryRecords } from "../hooks/useCatalog";

/**
 * `/admin/asset-categories` (P8-11): the category tree, the selected category's custom fields, and the manufacturer
 * and supplier lists. Reads and writes need `asset.update`; the API decides each call.
 */
export const AssetCategoriesPage: React.FC = () => {
  const [selectedId, setSelectedId] = useState("");
  const categories = useCategoryRecords("");
  const selected = categories.data?.find((category) => category.id === selectedId);

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold tracking-tight">{t("assets.categories.page_title")}</h1>
      <CategoryTree selectedId={selectedId} onSelect={setSelectedId} />
      {selected === undefined ? (
        <p className="text-sm text-muted">{t("assets.categories.select_hint")}</p>
      ) : (
        <CustomFieldsPanel key={selected.id} categoryId={selected.id} categoryName={selected.name} />
      )}
      <PartyList kind="manufacturers" />
      <PartyList kind="suppliers" />
    </div>
  );
};
