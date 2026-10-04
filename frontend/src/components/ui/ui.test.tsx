// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { t } from "@/lib/i18n";
import { DataTable, EmptyState, ErrorState, Skeleton, type Column } from ".";

describe("Skeleton", () => {
  it("announces loading once and renders the requested blocks", () => {
    const { container } = render(<Skeleton rows={4} />);
    expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText(t("ui.loading"))).toBeInTheDocument();
    expect(container.querySelectorAll("[aria-hidden='true']")).toHaveLength(4);
  });
});

describe("ErrorState", () => {
  it("says what went wrong and retries on request", async () => {
    const retry = vi.fn();
    render(<ErrorState message="The list could not be loaded." onRetry={retry} />);
    expect(screen.getByRole("alert")).toHaveTextContent(t("ui.error.title"));
    expect(screen.getByText("The list could not be loaded.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: t("ui.error.retry") }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("offers no retry button when there is nothing to retry", () => {
    render(<ErrorState />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("EmptyState", () => {
  it("offers the next step when there is one", async () => {
    const act = vi.fn();
    render(<EmptyState message="No teams yet." action={{ label: "Add a team", onClick: act }} />);
    expect(screen.getByText(t("ui.empty.title"))).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add a team" }));
    expect(act).toHaveBeenCalledOnce();
  });

  it("shows no button when the member cannot act", () => {
    render(<EmptyState title="Nothing assigned" />);
    expect(screen.getByText("Nothing assigned")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

interface Row {
  id: string;
  name: string;
  role: string;
}
const ROWS: Row[] = [
  { id: "1", name: "Ada", role: "Lead" },
  { id: "2", name: "Bob", role: "Member" },
];
const COLUMNS: Column<Row>[] = [
  { id: "name", header: "Name", cell: (row) => row.name },
  { id: "role", header: "Role", cell: (row) => row.role },
];

describe("DataTable", () => {
  it("renders a table with headers for wide screens", () => {
    render(<DataTable columns={COLUMNS} rows={ROWS} rowKey={(row) => row.id} caption="People" />);
    const table = screen.getByRole("table", { hidden: true });
    expect(table).toHaveClass("hidden", "md:table");
    expect(
      within(table)
        .getAllByRole("columnheader", { hidden: true })
        .map((h) => h.textContent),
    ).toEqual(["Name", "Role"]);
    expect(within(table).getAllByRole("row", { hidden: true })).toHaveLength(3);
  });

  it("also renders the same rows as cards that only show below md", () => {
    render(<DataTable columns={COLUMNS} rows={ROWS} rowKey={(row) => row.id} caption="People" />);
    const cards = screen.getByRole("list", { name: "People", hidden: true });
    expect(cards).toHaveClass("md:hidden");
    const items = within(cards).getAllByRole("listitem", { hidden: true });
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Ada");
    expect(items[0]).toHaveTextContent("Lead");
  });

  it("names itself for assistive technology, with a fallback", () => {
    render(<DataTable columns={COLUMNS} rows={[]} rowKey={(row) => row.id} />);
    expect(screen.getByText(t("ui.table.caption_fallback"), { selector: "caption" })).toBeInTheDocument();
  });
});
