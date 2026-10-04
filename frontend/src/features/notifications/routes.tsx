// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type { RouteObject } from "react-router";
import { placeholderRoute } from "@/app/routeHelpers";

// The inbox and preferences screens arrive in P7-05.
export const notificationRoutes: RouteObject[] = [
  placeholderRoute({ path: "notifications", titleKey: "nav.notifications", permission: "notification.read" }),
];
