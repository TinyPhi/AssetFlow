// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { envelope, server } from "@/test/server";
import { useAssetSearch } from "./useAssetDetail";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useAssetSearch", () => {
  it("asks the API once after the user stops typing, not on every keystroke", async () => {
    const queries: string[] = [];
    server.use(
      http.get("/api/v1/assets", ({ request }) => {
        queries.push(new URL(request.url).searchParams.get("q") ?? "");
        return HttpResponse.json(envelope({ items: [], next_cursor: null }));
      }),
    );

    const { result, rerender } = renderHook(({ text }) => useAssetSearch(text), {
      wrapper,
      initialProps: { text: "" },
    });
    for (const text of ["al", "alp", "alph", "alpha"]) rerender({ text });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });
    expect(queries).toEqual(["alpha"]);
  });
});
