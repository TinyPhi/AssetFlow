// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type { RouteObject } from "react-router";
import { RequireAuth } from "@/app/guards";
import { Layout } from "@/app/layout/Layout";
import { NotFoundPage } from "@/app/pages/NotFoundPage";
import { adminRoutes } from "@/features/admin/routes";
import { assetRoutes } from "@/features/assets/routes";
import { AuthCallbackPage, SignInPage } from "@/features/auth";
import { DashboardPage } from "@/features/dashboard/pages/DashboardPage";
import { maintenanceRoutes } from "@/features/maintenance/routes";
import { notificationRoutes } from "@/features/notifications/routes";
import { organizationRoutes } from "@/features/organization/routes";
import { settingsRoutes } from "@/features/settings/routes";

export function buildRoutes(): RouteObject[] {
  return [
    { path: "/sign-in", element: <SignInPage /> },
    { path: "/auth/callback", element: <AuthCallbackPage /> },
    {
      element: <RequireAuth />,
      children: [
        {
          element: <Layout />,
          children: [
            { index: true, element: <DashboardPage /> },
            ...organizationRoutes,
            ...assetRoutes,
            ...maintenanceRoutes,
            ...notificationRoutes,
            ...adminRoutes,
            ...settingsRoutes,
            { path: "*", element: <NotFoundPage /> },
          ],
        },
      ],
    },
  ];
}
