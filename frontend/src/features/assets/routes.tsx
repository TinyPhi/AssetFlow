// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type { RouteObject } from "react-router";
import { placeholderRoute } from "@/app/routeHelpers";

export const assetRoutes: RouteObject[] = [
  placeholderRoute({ path: "assets", titleKey: "nav.assets", permission: "asset.read", module: "assets" }),
];
