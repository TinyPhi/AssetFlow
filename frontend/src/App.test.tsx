// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AppContent } from "./App";
import { t } from "@/lib/i18n";

describe("App Component", () => {
  it("renders AssetFlow title and initialization status", () => {
    render(<AppContent />);
    expect(screen.getByRole("heading", { name: t("app.shell.title") })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(t("app.shell.status_ready"));
  });
});
