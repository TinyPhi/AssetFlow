// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type { RouteObject } from "react-router";
import { RequirePermission } from "@/app/guards";
import { NotificationsPage } from "./pages/NotificationsPage";

export const notificationRoutes: RouteObject[] = [
  {
    path: "notifications",
    element: (
      <RequirePermission permission="notification.read">
        <NotificationsPage />
      </RequirePermission>
    ),
  },
];
