import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import type { JiraSite } from "@/api/queries";
import { json, renderWithQueries, stubApi, type Routes } from "@/testing/api";
import { DEFAULT_WORKSPACE_ID } from "@/workspace";

import { hasMappedFields, JiraFieldsSheet } from "./jira-fields-sheet";

const SITE_PATH = `/workspaces/${DEFAULT_WORKSPACE_ID}/jira/sites/cloud-acme`;
const AC_FIELD = { id: "cf_100", name: "Acceptance criteria", type: "Paragraph", suggested: true };
const NOTES = { id: "cf_101", name: "Acceptance notes", type: "Short text", suggested: false };
const POINTS = { id: "cf_16", name: "Story point estimate", type: "Number", suggested: true };
const NONE = { acceptance_criteria: null, story_points: null };

const SITE: JiraSite = {
  cloud_id: "cloud-acme",
  url: "https://acme.atlassian.net",
  name: "Acme",
  enabled: true,
  projects: [
    { id: "10001", key: "API", name: "Public API", fields: NONE },
    {
      id: "10004",
      key: "WEB",
      name: "Web shop",
      fields: { acceptance_criteria: { id: "cf_gone", name: "Old AC" }, story_points: null },
    },
  ],
};

function fields(project: string): Routes {
  return {
    [`GET ${SITE_PATH}/fields?role=acceptance_criteria&project=${project}`]: () =>
      json(200, { fields: [AC_FIELD, NOTES] }),
    [`GET ${SITE_PATH}/fields?role=story_points&project=${project}`]: () =>
      json(200, { fields: [POINTS] }),
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderSheet(routes: Routes, onOpenChange = vi.fn()) {
  const fetch = stubApi(routes);
  renderWithQueries(
    <JiraFieldsSheet
      open
      site={SITE}
      workspaceId={DEFAULT_WORKSPACE_ID}
      baseUrl="http://api.test"
      onOpenChange={onOpenChange}
    />,
  );
  return { fetch, onOpenChange };
}

function options(name: string): string[] {
  const select = screen.getByRole("combobox", { name }) as HTMLSelectElement;
  return [...select.options].map((o) => o.textContent ?? "");
}

test("it offers the fields that fit each role, with their type", async () => {
  renderSheet(fields("API"));

  expect(screen.getByRole("heading", { name: "Fields of Acme" })).toBeDefined();
  await screen.findByRole("combobox", { name: "Story points" });
  expect(options("Acceptance criteria")).toEqual([
    "Not mapped",
    "Acceptance criteria · Paragraph · suggested",
    "Acceptance notes · Short text",
  ]);
  expect(options("Story points")).toEqual([
    "Not mapped",
    "Story point estimate · Number · suggested",
  ]);
});

test("saving sends the project's whole mapping", async () => {
  const saved: unknown[] = [];
  const { onOpenChange } = renderSheet({
    ...fields("API"),
    [`PUT ${SITE_PATH}/projects/API/fields`]: async (request) => {
      saved.push(await request.json());
      return json(200, { acceptance_criteria: { id: "cf_100", name: "Acceptance criteria" } });
    },
  });

  fireEvent.change(await screen.findByRole("combobox", { name: "Acceptance criteria" }), {
    target: { value: "cf_100" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save fields" }));

  await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  expect(saved).toEqual([{ acceptance_criteria: "cf_100", story_points: null }]);
});

test("a mapped field Jira no longer lists stays shown", async () => {
  renderSheet({ ...fields("API"), ...fields("WEB") });

  await screen.findByRole("combobox", { name: "Story points" });
  fireEvent.change(screen.getByRole("combobox", { name: "Project" }), {
    target: { value: "WEB" },
  });

  await waitFor(() =>
    expect(options("Acceptance criteria")).toContain("Old AC · no longer in Jira"),
  );
  const select = screen.getByRole("combobox", { name: "Acceptance criteria" }) as HTMLSelectElement;
  expect(select.value).toBe("cf_gone");
});

test("a refused save stays open with the reason", async () => {
  const { onOpenChange } = renderSheet({
    ...fields("API"),
    [`PUT ${SITE_PATH}/projects/API/fields`]: () =>
      json(422, {
        detail: { code: "field_type_mismatch", message: "Story points (Option) cannot hold it" },
      }),
  });

  await screen.findByRole("combobox", { name: "Story points" });
  fireEvent.click(screen.getByRole("button", { name: "Save fields" }));

  expect(await screen.findByText("Story points (Option) cannot hold it")).toBeDefined();
  expect(onOpenChange).not.toHaveBeenCalled();
});

test("a role with no fitting field says how to add one", async () => {
  renderSheet({
    [`GET ${SITE_PATH}/fields?role=acceptance_criteria&project=API`]: () =>
      json(200, { fields: [] }),
    [`GET ${SITE_PATH}/fields?role=story_points&project=API`]: () =>
      json(502, { detail: "Atlassian answered 500" }),
  });

  expect(await screen.findByText(/has no paragraph or short-text field/)).toBeDefined();
  expect(await screen.findByRole("button", { name: "Retry" })).toBeDefined();
});

test("a project maps fields when either role is set", () => {
  expect(hasMappedFields(SITE.projects[0]!)).toBe(false);
  expect(hasMappedFields(SITE.projects[1]!)).toBe(true);
});
