// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import type React from "react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { ToastProvider } from "@/app/ToastProvider";
import { buildRoutes } from "@/app/routes";
import { setAccessToken } from "@/lib/auth";
import type { Me } from "@/lib/permissions";
import { meHandler, makeMe, server } from "./server";

export function newQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
}

/** Render the whole app at `path`, signed in as a member with `me` (or signed out with `signedIn: false`). */
export function renderApp(path = "/", options: { me?: Partial<Me>; signedIn?: boolean } = {}): RenderResult {
  if (options.signedIn !== false) setAccessToken("test-token");
  server.use(meHandler(makeMe(options.me)));
  const router = createMemoryRouter(buildRoutes(), { initialEntries: [path] });
  return render(
    <QueryClientProvider client={newQueryClient()}>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

/** Wrap a component in the providers hooks need (query client, toasts). */
export function withProviders(ui: React.ReactElement): RenderResult {
  return render(
    <QueryClientProvider client={newQueryClient()}>
      <ToastProvider>{ui}</ToastProvider>
    </QueryClientProvider>,
  );
}
