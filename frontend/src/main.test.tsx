// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { StrictMode, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

const rendered: ReactNode[] = [];

vi.mock("react-dom/client", () => ({
  default: {
    createRoot: () => ({
      render: (node: ReactNode) => {
        rendered.push(node);
      },
    }),
  },
}));
vi.mock("./App", () => ({ default: () => null }));

describe("main", () => {
  it("renders the app inside React.StrictMode", async () => {
    document.body.innerHTML = '<div id="root"></div>';
    await import("./main");
    expect(rendered).toHaveLength(1);
    expect(rendered[0]).toMatchObject({ type: StrictMode });
  });
});
