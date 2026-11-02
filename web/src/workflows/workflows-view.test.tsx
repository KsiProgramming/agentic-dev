import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { json, renderWithQueries, stubApi } from "@/testing/api";
import { DEFAULT_WORKSPACE_ID } from "@/workspace";

import type { WorkflowSummary } from "./api";
import { WorkflowsView } from "./workflows-view";

const navigation = vi.hoisted(() => ({
  search: new URLSearchParams(),
  replace: vi.fn(),
  push: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => navigation.search,
  usePathname: () => "/workflows",
  useRouter: () => ({ replace: navigation.replace, push: navigation.push }),
}));

const LIST = `GET /workflows?workspace_id=${DEFAULT_WORKSPACE_ID}`;
const NOTES: WorkflowSummary = {
  workflow_id: "release-notes",
  name: "Release notes",
  description: "Writes them.",
  latest_version: 2,
  created_at: "2026-11-01T10:00:00Z",
  updated_at: "2026-11-02T10:00:00Z",
};

beforeEach(() => {
  navigation.search = new URLSearchParams();
  navigation.replace.mockReset();
});
afterEach(() => vi.unstubAllGlobals());

function show() {
  return renderWithQueries(<WorkflowsView baseUrl="http://api.test" />);
}

test("each workflow links to the builder with its id, version and last change", async () => {
  stubApi({ [LIST]: () => json(200, { items: [NOTES] }) });
  show();

  const table = within(await screen.findByRole("table", { name: "Workflows" }));
  expect(table.getByRole("link", { name: "Release notes" }).getAttribute("href")).toBe(
    "/workflows/release-notes",
  );
  expect(table.getByText("release-notes")).toBeDefined();
  expect(table.getByText("Version 2")).toBeDefined();
  expect(table.getByText("Writes them.")).toBeDefined();

  fireEvent.click(screen.getByRole("button", { name: "New workflow" }));
  expect(navigation.replace).toHaveBeenCalledWith("/workflows?blank=1", { scroll: false });
});

test("no workflows: one sentence and New workflow", async () => {
  stubApi({ [LIST]: () => json(200, { items: [] }) });
  show();

  expect(await screen.findByText("No workflows yet.")).toBeDefined();
  expect(screen.getAllByRole("button", { name: "New workflow" })).toHaveLength(1);
});

test("a failed load says so and retries", async () => {
  let answer = () => json(500, { detail: "Boom" });
  stubApi({ [LIST]: () => answer() });
  show();

  expect(await screen.findByText("Boom")).toBeDefined();
  answer = () => json(200, { items: [NOTES] });
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByRole("table", { name: "Workflows" })).toBeDefined();
});

test("?blank=1 opens the new workflow sheet", async () => {
  stubApi({
    [LIST]: () => json(200, { items: [] }),
    "GET /node-types": () => json(200, []),
    [`GET /workspaces/${DEFAULT_WORKSPACE_ID}/connections`]: () => json(200, []),
  });
  navigation.search = new URLSearchParams({ blank: "1" });
  show();

  expect(await screen.findByTestId("new-workflow-sheet")).toBeDefined();
});
