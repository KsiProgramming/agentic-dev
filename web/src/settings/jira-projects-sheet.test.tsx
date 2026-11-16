import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import type { JiraSite } from "@/api/queries";
import { json, renderWithQueries, requested, stubApi, type Routes } from "@/testing/api";
import { DEFAULT_WORKSPACE_ID } from "@/workspace";

import { JiraProjectsSheet } from "./jira-projects-sheet";

const PROJECTS_PATH = `/workspaces/${DEFAULT_WORKSPACE_ID}/jira/sites/cloud-acme/projects`;
const API_PROJECT = { id: "10001", key: "API", name: "Public API" };
const DOCS = { id: "10002", key: "DOCS", name: "Documentation" };
const WEB = { id: "10004", key: "WEB", name: "Web shop" };

const SITE: JiraSite = {
  cloud_id: "cloud-acme",
  url: "https://acme.atlassian.net",
  name: "Acme",
  enabled: true,
  projects: [WEB],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderSheet(routes: Routes, onOpenChange = vi.fn()) {
  const fetch = stubApi(routes);
  renderWithQueries(
    <JiraProjectsSheet
      open
      site={SITE}
      workspaceId={DEFAULT_WORKSPACE_ID}
      baseUrl="http://api.test"
      onOpenChange={onOpenChange}
    />,
  );
  return { fetch, onOpenChange };
}

function rows() {
  return within(screen.getByRole("list", { name: "Projects" })).getAllByRole("listitem");
}

test("it lists the site's projects with the picked ones checked", async () => {
  renderSheet({
    [`GET ${PROJECTS_PATH}`]: () =>
      json(200, { projects: [DOCS, API_PROJECT, WEB], next_cursor: null }),
  });

  expect(await screen.findByRole("checkbox", { name: /Web shop/ })).toBeDefined();
  expect(screen.getByRole("heading", { name: "Projects of Acme" })).toBeDefined();
  expect(rows().map((li) => li.textContent)).toEqual([
    "DOCSDocumentation",
    "APIPublic API",
    "WEBWeb shop",
  ]);
  expect(screen.getByRole("checkbox", { name: /Web shop/ }).getAttribute("aria-checked")).toBe(
    "true",
  );
  expect(screen.getByRole("checkbox", { name: /Public API/ }).getAttribute("aria-checked")).toBe(
    "false",
  );
  expect(screen.getByText("1 selected")).toBeDefined();
});

test("saving sends every picked project, also one the search no longer lists", async () => {
  const saved: unknown[] = [];
  const { fetch, onOpenChange } = renderSheet({
    [`GET ${PROJECTS_PATH}`]: () =>
      json(200, { projects: [DOCS, API_PROJECT, WEB], next_cursor: null }),
    [`GET ${PROJECTS_PATH}?q=doc`]: () => json(200, { projects: [DOCS], next_cursor: null }),
    [`PUT ${PROJECTS_PATH}`]: async (request) => {
      saved.push(await request.json());
      return json(200, { ...SITE, projects: [DOCS, WEB] });
    },
  });

  await screen.findByRole("checkbox", { name: /Web shop/ });
  fireEvent.change(screen.getByRole("searchbox", { name: "Search projects" }), {
    target: { value: "doc" },
  });
  await waitFor(() => expect(requested(fetch)).toContain(`GET ${PROJECTS_PATH}?q=doc`));
  await waitFor(() => expect(rows()).toHaveLength(1));
  fireEvent.click(screen.getByRole("checkbox", { name: /Documentation/ }));
  expect(screen.getByText("2 selected")).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Save projects" }));

  await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  expect(saved).toEqual([{ project_ids: ["10004", "10002"] }]);
});

test("a search with no match says so", async () => {
  renderSheet({
    [`GET ${PROJECTS_PATH}`]: () => json(200, { projects: [], next_cursor: null }),
  });

  expect(await screen.findByText("This site has no projects you can see.")).toBeDefined();
});

test("a long list says it is cut and to search", async () => {
  renderSheet({
    [`GET ${PROJECTS_PATH}`]: () => json(200, { projects: [DOCS, WEB], next_cursor: 2 }),
  });

  expect(await screen.findByText("Showing the first 2. Search to find the others.")).toBeDefined();
});

test("a failed load can be retried, and a refused save stays open with the reason", async () => {
  const routes: Routes = {
    [`GET ${PROJECTS_PATH}`]: () => json(502, { detail: "Atlassian answered 503" }),
    [`PUT ${PROJECTS_PATH}`]: () =>
      json(422, { detail: { code: "unknown_project", message: "not a project: 10004" } }),
  };
  const { onOpenChange } = renderSheet(routes);

  expect((await screen.findByRole("alert")).textContent).toBe("Atlassian answered 503");
  routes[`GET ${PROJECTS_PATH}`] = () => json(200, { projects: [WEB], next_cursor: null });
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await screen.findByRole("checkbox", { name: /Web shop/ });
  fireEvent.click(screen.getByRole("button", { name: "Save projects" }));

  expect(await screen.findByText("not a project: 10004")).toBeDefined();
  expect(onOpenChange).not.toHaveBeenCalled();
});

test("cancel closes without saving", async () => {
  const { fetch, onOpenChange } = renderSheet({
    [`GET ${PROJECTS_PATH}`]: () => json(200, { projects: [WEB], next_cursor: null }),
  });

  await screen.findByRole("checkbox", { name: /Web shop/ });
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

  expect(onOpenChange).toHaveBeenCalledWith(false);
  expect(requested(fetch)).not.toContain(`PUT ${PROJECTS_PATH}`);
});
