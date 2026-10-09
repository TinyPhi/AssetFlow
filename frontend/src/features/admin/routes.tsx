// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type { RouteObject } from "react-router";
import { RequirePermission } from "@/app/guards";
import { AccessViewPage } from "./pages/AccessViewPage";
import { DeliveryLogPage } from "./pages/DeliveryLogPage";
import { ModulesPage } from "./pages/ModulesPage";
import { NotificationChannelsPage } from "./pages/NotificationChannelsPage";
import { OrganizationSettingsPage } from "./pages/OrganizationSettingsPage";

export const adminRoutes: RouteObject[] = [
  {
    path: "admin",
    element: (
      <RequirePermission permission="role_grant.read">
        <OrganizationSettingsPage />
      </RequirePermission>
    ),
  },
  {
    path: "admin/settings",
    element: (
      <RequirePermission permission="role_grant.read">
        <OrganizationSettingsPage />
      </RequirePermission>
    ),
  },
  {
    path: "admin/modules",
    element: (
      <RequirePermission permission="role_grant.read">
        <ModulesPage />
      </RequirePermission>
    ),
  },
  {
    path: "admin/access/:memberId",
    element: (
      <RequirePermission permission="role_grant.read">
        <AccessViewPage />
      </RequirePermission>
    ),
  },
  {
    path: "admin/notification-channels",
    element: (
      <RequirePermission permission="notification_channel.read">
        <NotificationChannelsPage />
      </RequirePermission>
    ),
  },
  {
    path: "admin/notification-channels/deliveries",
    element: (
      <RequirePermission permission="notification_delivery.read">
        <DeliveryLogPage />
      </RequirePermission>
    ),
  },
];
