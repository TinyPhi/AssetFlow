// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "@/app/AppShell";
import { ToastProvider } from "@/app/ToastProvider";
import { t } from "@/lib/i18n";

function mockHealth(status: number, body: unknown): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify(body), { status })));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderShell(): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <AppShell />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AppShell", () => {
  it("shows ready only when public health reports ok", async () => {
    const fetchMock = mockHealth(200, { status: "ok" });
    renderShell();
    expect(screen.getAllByText(t("app.shell.title"))[0]).toBeInTheDocument();
    expect(screen.getByText(t("app.shell.online"))).toBeInTheDocument();
    expect(await screen.findByText(t("app.shell.status_ready"))).toBeInTheDocument();
    expect(screen.getByText(t("app.shell.health_ok"))).toBeInTheDocument();
    expect(screen.getByText(t("app.shell.footer"))).toBeInTheDocument();
    expect(fetchMock.mock.calls.every(([url]) => url === "/api/health")).toBe(true);
  });

  it("shows an error state and not ready when health returns 503", async () => {
    mockHealth(503, { status: "unhealthy" });
    renderShell();
    // The health query retries once (about 1s) before surfacing the error.
    expect(await screen.findByText(t("app.shell.health_error"), {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByText(t("app.shell.status_not_ready"))).toBeInTheDocument();
    expect(screen.queryByText(t("app.shell.status_ready"))).not.toBeInTheDocument();
    expect(screen.queryByText(t("app.shell.health_ok"))).not.toBeInTheDocument();
  });

  it("shows an unhealthy state when status is not ok", async () => {
    mockHealth(200, { status: "degraded" });
    renderShell();
    expect(await screen.findByText(t("app.shell.health_unhealthy"))).toBeInTheDocument();
    expect(screen.queryByText(t("app.shell.status_ready"))).not.toBeInTheDocument();
  });

  it("gives the icon-only refresh button an accessible name", async () => {
    mockHealth(200, { status: "ok" });
    renderShell();
    await screen.findByText(t("app.shell.health_ok"));
    expect(screen.getByRole("button", { name: t("app.shell.health_refresh") })).toBeInTheDocument();
  });

  it("raises a toast when network status changes", async () => {
    mockHealth(200, { status: "ok" });
    renderShell();
    expect(screen.queryByText(t("app.toast.network_offline"))).not.toBeInTheDocument();
    act(() => {
      window.dispatchEvent(new Event("offline"));
    });
    expect(await screen.findByText(t("app.toast.network_offline"))).toBeInTheDocument();
    expect(screen.getByText(t("app.shell.offline"))).toBeInTheDocument();
    act(() => {
      window.dispatchEvent(new Event("online"));
    });
    await waitFor(() => {
      expect(screen.getByText(t("app.toast.network_online"))).toBeInTheDocument();
    });
  });
});
