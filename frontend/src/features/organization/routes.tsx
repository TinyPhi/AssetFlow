// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type { RouteObject } from "react-router";
import { placeholderRoute } from "@/app/routeHelpers";

// Organization structure and people (M1.6-T4): P7-04b/c replace each placeholder with its screen.
export const organizationRoutes: RouteObject[] = [
  placeholderRoute({ path: "organization", titleKey: "nav.organization", permission: "org_unit.read" }),
  placeholderRoute({ path: "teams", titleKey: "nav.teams", permission: "team.read" }),
  placeholderRoute({ path: "members", titleKey: "nav.members", permission: "member.read" }),
];
