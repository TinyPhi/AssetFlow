// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type { RouteObject } from "react-router";
import { RequireModule, RequirePermission } from "@/app/guards";

/** `/assets`: the asset list, behind `asset.read` and the installed `assets` module; its code loads on first visit. */
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
];
