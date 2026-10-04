// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type { RouteObject } from "react-router";
import { placeholderRoute } from "@/app/routeHelpers";

// Access view, modules and organization settings (P7-04d), schema-driven forms (P7-06).
export const adminRoutes: RouteObject[] = [
  placeholderRoute({ path: "admin", titleKey: "nav.admin", permission: "role_grant.read" }),
];
