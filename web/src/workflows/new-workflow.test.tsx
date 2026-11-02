import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import {
  CLAUDE,
  CONNECTIONS_PATH,
  json,
  renderWithQueries,
  stubApi,
  type Routes,
} from "@/testing/api";
import { DEFAULT_WORKSPACE_ID } from "@/workspace";

import type { NodeManifest } from "./node-types";
import { agentProviders, NewWorkflowSheet, slugify } from "./new-workflow";

const navigation = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: navigation.push, replace: vi.fn() }),
}));

// The ids the engine's `workflow_slug` gives (test_blank_workflow.py runs the same cases).
const SLUGS = JSON.parse(
  readFileSync(resolve(__dirname, "../../../schemas/fixtures/workflow-slugs.json"), "utf8"),
) as { cases: { name: string; slug: string }[] };
const NODE_TYPES = JSON.parse(
  readFileSync(resolve(__dirname, "../../../schemas/fixtures/node-types.json"), "utf8"),
) as NodeManifest[];

const CREATE = `POST /workflows?workspace_id=${DEFAULT_WORKSPACE_ID}`;

beforeEach(() => navigation.push.mockReset());
afterEach(() => vi.unstubAllGlobals());

describe("slugify", () => {
  test.each(SLUGS.cases)("$name is $slug, as the engine makes it", ({ name, slug }) => {
    expect(slugify(name)).toBe(slug);
  });
});

test("the providers are the agent manifest's", () => {
  expect(agentProviders(NODE_TYPES)).toEqual(["claude"]);
  expect(agentProviders([])).toEqual([]);
});

function routes(extra: Routes = {}): Routes {
  return {
    "GET /node-types": () => json(200, NODE_TYPES),
    [`GET ${CONNECTIONS_PATH}`]: () => json(200, [CLAUDE]),
    ...extra,
  };
}

function show() {
  renderWithQueries(
    <NewWorkflowSheet
      open
      onOpenChange={() => {}}
      workspaceId={DEFAULT_WORKSPACE_ID}
      baseUrl="http://api.test"
    />,
  );
  return within(screen.getByTestId("new-workflow-sheet"));
}

test("the id follows the name until it is edited", async () => {
  stubApi(routes());
  const sheet = show();

  fireEvent.change(sheet.getByLabelText("Name"), { target: { value: "Release notes" } });
  expect(sheet.getByLabelText("Id")).toHaveProperty("value", "release-notes");

  fireEvent.change(sheet.getByLabelText("Id"), { target: { value: "notes" } });
  fireEvent.change(sheet.getByLabelText("Name"), { target: { value: "Release notes v2" } });
  expect(sheet.getByLabelText("Id")).toHaveProperty("value", "notes");
});

test("a missing name and a bad id are shown on their fields, and nothing is sent", async () => {
  const fetch = stubApi(routes());
  const sheet = show();

  fireEvent.change(sheet.getByLabelText("Id"), { target: { value: "Not an id" } });
  fireEvent.click(sheet.getByRole("button", { name: "Create workflow" }));

  expect(await sheet.findByText("Give the workflow a name.")).toBeDefined();
  expect(sheet.getByText(/Use lower-case letters/)).toBeDefined();
  expect(sheet.getByLabelText("Id").getAttribute("aria-invalid")).toBe("true");
  expect(fetch.mock.calls.some(([r]) => r.method === "POST")).toBe(false);
});

test("Claude is chosen and connected; Copilot is listed but not available yet", async () => {
  stubApi(routes());
  const sheet = show();

  const claude = await sheet.findByRole("radio", { name: /Claude/ });
  expect(claude).toHaveProperty("checked", true);
  await waitFor(() => expect(claude.closest("label")?.textContent).toContain("Connected"));
  const copilot = sheet.getByRole("radio", { name: /GitHub Copilot/ });
  expect(copilot).toHaveProperty("disabled", true);
  expect(sheet.getByText("Comes with the Copilot adapter.")).toBeDefined();
});

test("a provider that is not connected can be chosen, with how to connect it", async () => {
  stubApi(routes({ [`GET ${CONNECTIONS_PATH}`]: () => json(200, []) }));
  const sheet = show();

  expect(await sheet.findByText(/Claude is not connected/)).toBeDefined();
  expect(sheet.getByRole("link", { name: "Integrations" }).getAttribute("href")).toBe(
    "/settings/integrations",
  );
  expect(sheet.getByRole("button", { name: "Create workflow" })).toHaveProperty("disabled", false);
});

test("creating sends the blank workflow and opens it with its starter agent", async () => {
  const fetch = stubApi(
    routes({ [CREATE]: () => json(201, { workflow_id: "release-notes", version: 1 }) }),
  );
  const sheet = show();
  await sheet.findByRole("radio", { name: /Claude/ });

  fireEvent.change(sheet.getByLabelText("Name"), { target: { value: " Release notes " } });
  fireEvent.change(sheet.getByLabelText("Description (optional)"), {
    target: { value: "Writes them." },
  });
  fireEvent.click(sheet.getByRole("button", { name: "Create workflow" }));

  await waitFor(() =>
    expect(navigation.push).toHaveBeenCalledWith("/workflows/release-notes?node=agent_1"),
  );
  const post = fetch.mock.calls.find(([r]) => r.method === "POST")?.[0];
  expect(await post?.json()).toEqual({
    blank: {
      name: "Release notes",
      id: "release-notes",
      description: "Writes them.",
      provider: "claude",
    },
  });
});

test("an id that exists is shown on the field, with a link to it", async () => {
  stubApi(
    routes({
      [CREATE]: () =>
        json(409, {
          detail: { code: "workflow_exists", message: "exists", workflow_id: "release-notes" },
        }),
    }),
  );
  const sheet = show();

  fireEvent.change(sheet.getByLabelText("Name"), { target: { value: "Release notes" } });
  fireEvent.click(sheet.getByRole("button", { name: "Create workflow" }));

  expect(await sheet.findByText(/A workflow with this id exists/)).toBeDefined();
  expect(sheet.getByRole("link", { name: "Open it" }).getAttribute("href")).toBe(
    "/workflows/release-notes",
  );
  expect(navigation.push).not.toHaveBeenCalled();
});

test("a field the server refuses is shown on it; anything else above the footer", async () => {
  let answer = json(422, {
    detail: [{ loc: ["body", "blank", "description"], msg: "Too long", type: "string_too_long" }],
  });
  stubApi(routes({ [CREATE]: () => answer }));
  const sheet = show();
  fireEvent.change(sheet.getByLabelText("Name"), { target: { value: "Notes" } });

  fireEvent.click(sheet.getByRole("button", { name: "Create workflow" }));
  expect(await sheet.findByText("Too long")).toBeDefined();

  answer = json(500, { detail: "Boom" });
  fireEvent.click(sheet.getByRole("button", { name: "Create workflow" }));
  expect(await sheet.findByText("Boom")).toBeDefined();
});
