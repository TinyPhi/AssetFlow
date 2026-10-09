// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import type { RouteObject } from "react-router";
import { RequireModule, RequirePermission } from "@/app/guards";
import type { TranslationKey } from "@/lib/i18n";
import type { ModuleKey } from "@/lib/permissions";

interface PlaceholderRoute {
  path: string;
  titleKey: TranslationKey;
  permission?: string;
  module?: ModuleKey;
}

function guarded(route: PlaceholderRoute, page: React.ReactElement): React.ReactElement {
  let element = page;
  if (route.module !== undefined) {
    element = <RequireModule module={route.module}>{element}</RequireModule>;
  }
  if (route.permission !== undefined) {
    element = <RequirePermission permission={route.permission}>{element}</RequirePermission>;
  }
  return element;
}

/**
 * A lazily loaded screen behind the guards its feature needs, for a feature that is not built yet.
 * The page code is split into its own chunk and only fetched when the route is visited; a feature
 * replaces its placeholder with its real page the same way.
 */
export function placeholderRoute(route: PlaceholderRoute): RouteObject {
  return {
    path: route.path,
    lazy: async () => {
      const { ComingSoonPage } = await import("@/app/pages/ComingSoonPage");
      return { element: guarded(route, <ComingSoonPage titleKey={route.titleKey} />) };
    },
  };
}
