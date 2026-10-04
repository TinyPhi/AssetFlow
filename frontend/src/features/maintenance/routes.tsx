// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type { RouteObject } from "react-router";
import { placeholderRoute } from "@/app/routeHelpers";

export const maintenanceRoutes: RouteObject[] = [
  placeholderRoute({
    path: "maintenance",
    titleKey: "nav.items.maintenance",
    permission: "work_order.read",
    module: "maintenance",
  }),
];
