// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { HealthStatus } from "@/app/HealthStatus";
import { t } from "@/lib/i18n";
import { server } from "@/test/server";
import { withProviders } from "@/test/render";

describe("HealthStatus", () => {
  it("shows the platform operational when public health reports ok", async () => {
    withProviders(<HealthStatus />);
    expect(await screen.findByText(t("app.shell.health_ok"))).toBeInTheDocument();
  });

  it("shows an unhealthy state when the status is not ok", async () => {
    server.use(http.get("/api/health", () => HttpResponse.json({ status: "degraded" })));
    withProviders(<HealthStatus />);
    expect(await screen.findByText(t("app.shell.health_unhealthy"))).toBeInTheDocument();
    expect(screen.queryByText(t("app.shell.health_ok"))).not.toBeInTheDocument();
  });

  it("shows an error state when health returns 503", async () => {
    server.use(http.get("/api/health", () => HttpResponse.json({ status: "unhealthy" }, { status: 503 })));
    withProviders(<HealthStatus />);
    // The hook retries once after a one-second pause before it reports the error.
    expect(await screen.findByText(t("app.shell.health_error"), {}, { timeout: 3000 })).toBeInTheDocument();
  });

  it("gives the icon-only refresh button an accessible name", async () => {
    withProviders(<HealthStatus />);
    await screen.findByText(t("app.shell.health_ok"));
    expect(screen.getByRole("button", { name: t("app.shell.health_refresh") })).toBeInTheDocument();
  });
});
