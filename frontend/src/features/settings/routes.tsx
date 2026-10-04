// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type { RouteObject } from "react-router";
import { placeholderRoute } from "@/app/routeHelpers";

// "My settings": every signed-in member, so no permission is needed.
export const settingsRoutes: RouteObject[] = [
  placeholderRoute({ path: "settings", titleKey: "nav.my_settings" }),
];
