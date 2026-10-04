// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// The route tree (§C4.9): the app composes each feature's own routes; feature pages are loaded lazily.
import type { RouteObject } from "react-router";
import { RequireAuth } from "@/app/guards";
import { Layout } from "@/app/layout/Layout";
import { DashboardPage } from "@/app/pages/DashboardPage";
import { NotFoundPage } from "@/app/pages/NotFoundPage";
import { SignInPage } from "@/app/pages/SignInPage";
import { adminRoutes } from "@/features/admin/routes";
import { assetRoutes } from "@/features/assets/routes";
import { maintenanceRoutes } from "@/features/maintenance/routes";
import { notificationRoutes } from "@/features/notifications/routes";
import { organizationRoutes } from "@/features/organization/routes";
import { settingsRoutes } from "@/features/settings/routes";

export function buildRoutes(): RouteObject[] {
  return [
    { path: "/sign-in", element: <SignInPage /> },
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
