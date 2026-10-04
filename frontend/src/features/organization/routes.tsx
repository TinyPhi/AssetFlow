// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type { RouteObject } from "react-router";
import { RequirePermission } from "@/app/guards";
import { LocationsPage } from "./pages/LocationsPage";
import { MemberProfilePage } from "./pages/MemberProfilePage";
import { MembersPage } from "./pages/MembersPage";
import { OrgChartPage } from "./pages/OrgChartPage";
import { TeamsPage } from "./pages/TeamsPage";

export const organizationRoutes: RouteObject[] = [
  {
    path: "organization",
    element: (
      <RequirePermission permission="org_unit.read">
        <OrgChartPage />
      </RequirePermission>
    ),
  },
  {
    path: "locations",
    element: (
      <RequirePermission permission="location.read">
        <LocationsPage />
      </RequirePermission>
    ),
  },
  {
    path: "teams",
    element: (
      <RequirePermission permission="team.read">
        <TeamsPage />
      </RequirePermission>
    ),
  },
  {
    path: "members",
    element: (
      <RequirePermission permission="member.read">
        <MembersPage />
      </RequirePermission>
    ),
  },
  {
    path: "members/:memberId",
    element: (
      <RequirePermission permission="member.read">
        <MemberProfilePage />
      </RequirePermission>
    ),
  },
];
