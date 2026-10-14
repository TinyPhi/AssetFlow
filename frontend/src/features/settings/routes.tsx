// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type { RouteObject } from "react-router";
import { NotificationPreferencesPage } from "./pages/NotificationPreferencesPage";

export const settingsRoutes: RouteObject[] = [
  {
    path: "settings",
    element: <NotificationPreferencesPage />,
  },
  {
    path: "settings/notifications",
    element: <NotificationPreferencesPage />,
  },
];
