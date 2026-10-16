// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type { RouteObject } from "react-router";
import { RequireModule, RequirePermission } from "@/app/guards";

/**
 * The asset screens, each behind its permission and the installed `assets` module; their code loads on first
 * visit. `assets/new` is declared before `assets/:id` (React Router ranks it first either way).
 */
export const assetRoutes: RouteObject[] = [
  {
    path: "assets",
    lazy: async () => {
      const { AssetsPage } = await import("./pages/AssetsPage");
      return {
        element: (
          <RequirePermission permission="asset.read">
            <RequireModule module="assets">
              <AssetsPage />
            </RequireModule>
          </RequirePermission>
        ),
      };
    },
  },
  {
    path: "assets/new",
    lazy: async () => {
      const { NewAssetPage } = await import("./pages/NewAssetPage");
      return {
        element: (
          <RequirePermission permission="asset.create">
            <RequireModule module="assets">
              <NewAssetPage />
            </RequireModule>
          </RequirePermission>
        ),
      };
    },
  },
  {
    path: "assets/:id",
    lazy: async () => {
      const { AssetDetailPage } = await import("./pages/AssetDetailPage");
      return {
        element: (
          <RequirePermission permission="asset.read">
            <RequireModule module="assets">
              <AssetDetailPage />
            </RequireModule>
          </RequirePermission>
        ),
      };
    },
  },
  {
    path: "admin/asset-categories",
    lazy: async () => {
      const { AssetCategoriesPage } = await import("./pages/AssetCategoriesPage");
      return {
        element: (
          <RequirePermission permission="asset.update">
            <RequireModule module="assets">
              <AssetCategoriesPage />
            </RequireModule>
          </RequirePermission>
        ),
      };
    },
  },
];
