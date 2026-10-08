// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type React from "react";
import { createBrowserRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { ToastProvider } from "@/app/ToastProvider";
import { buildRoutes } from "@/app/routes";
import { ProblemError } from "@/lib/api";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      // A refusal (4xx) will not change by asking again; only a network or server failure is retried.
      retry: (failureCount, error) =>
        !(error instanceof ProblemError && error.status < 500) && failureCount < 1,
    },
  },
});

const router = createBrowserRouter(buildRoutes());

export const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </QueryClientProvider>
  );
};

export default App;
