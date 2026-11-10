import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import {
  CLAUDE,
  CONNECTIONS_PATH,
  GITHUB,
  json,
  renderWithQueries,
  REPOS,
  REPOS_PATH,
  stubApi,
} from "@/testing/api";
import type { WorkflowSpec } from "@/runs/graph/spec-graph";
import { DEFAULT_WORKSPACE_ID } from "@/workspace";

import { WorkflowRunSheet } from "./new-run-sheet";
import { workflowRequires } from "./readiness";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

const RUN_ID = "00000000-0000-0000-0000-0000000000b2";

const spec = (steps: unknown[]) =>
  ({ id: "docs", name: "Docs", root: { type: "sequence", id: "main", steps } }) as WorkflowSpec;

test("a stored workflow needs Claude for its agents and GitHub for repo tools", () => {
  const writer = { type: "agent", id: "w", role: "w", instructions: "Write." };
  expect(workflowRequires(spec([writer]))).toEqual(["claude"]);
  expect(workflowRequires(spec([{ ...writer, tools: ["repo.read"] }]))).toEqual([
    "claude",
    "github",
  ]);
  expect(workflowRequires(spec([{ type: "tool", id: "t", tool: "scan.secrets" }]))).toEqual([
    "github",
  ]);
});

test("starting runs the stored version with its input, then opens the run", async () => {
  const fetch = stubApi({
    [`GET ${CONNECTIONS_PATH}`]: () => json(200, [CLAUDE, GITHUB]),
    [`GET ${REPOS_PATH}`]: () => json(200, REPOS),
    "POST /runs": () => json(202, { run_id: RUN_ID }),
  });
  const navigate = vi.fn();
  renderWithQueries(
    <WorkflowRunSheet
      open
      onOpenChange={() => {}}
      workflow={{ id: "docs", version: 2, name: "Docs", requires: ["claude", "github"] }}
      workspaceId={DEFAULT_WORKSPACE_ID}
      baseUrl="http://api.test"
      navigate={navigate}
    />,
  );
  const sheet = within(screen.getByTestId("workflow-run-sheet"));

  expect(sheet.getByRole("heading", { name: "New run: Docs" })).toBeDefined();
  expect(sheet.getByText(/Runs version 2 of/).textContent).toBe("Runs version 2 of docs.");
  fireEvent.click(await sheet.findByRole("combobox", { name: "Repository" }));
  fireEvent.click(await screen.findByRole("option", { name: /acme\/web/ }));
  fireEvent.change(sheet.getByLabelText("Input"), { target: { value: "Cover the API." } });
  fireEvent.click(sheet.getByRole("button", { name: "Start run" }));

  await waitFor(() => expect(navigate).toHaveBeenCalledWith(`/runs/${RUN_ID}`));
  const post = fetch.mock.calls.find(([r]) => r.method === "POST")?.[0];
  expect(await post?.json()).toEqual({
    stored_workflow: { id: "docs", version: 2 },
    input: "Cover the API.",
    repo: { url: "https://github.com/acme/web" },
    workspace_id: DEFAULT_WORKSPACE_ID,
    trigger: "manual",
    budget_usd: null,
  });
});

test("a workflow that needs an input names it, shows its example and will not start without it", async () => {
  const fetch = stubApi({
    [`GET ${CONNECTIONS_PATH}`]: () => json(200, [CLAUDE, GITHUB]),
    [`GET ${REPOS_PATH}`]: () => json(200, REPOS),
    "POST /runs": () => json(202, { run_id: RUN_ID }),
  });
  const navigate = vi.fn();
  renderWithQueries(
    <WorkflowRunSheet
      open
      onOpenChange={() => {}}
      workflow={{
        id: "team-review-pr",
        version: 2,
        name: "Team change",
        requires: ["claude", "github"],
        input: {
          required: true,
          label: "What should the team change?",
          description: "The change to make, in a few sentences.",
          example: "Add rate limiting to the login endpoint.",
        },
      }}
      workspaceId={DEFAULT_WORKSPACE_ID}
      baseUrl="http://api.test"
      navigate={navigate}
    />,
  );
  const sheet = within(screen.getByTestId("workflow-run-sheet"));
  fireEvent.click(await sheet.findByRole("combobox", { name: "Repository" }));
  fireEvent.click(await screen.findByRole("option", { name: /acme\/web/ }));

  const field = sheet.getByLabelText("What should the team change?");
  expect(field.getAttribute("placeholder")).toBe("e.g. Add rate limiting to the login endpoint.");
  expect(field.getAttribute("aria-required")).toBe("true");
  expect(sheet.getByText("The change to make, in a few sentences.")).toBeDefined();

  fireEvent.click(sheet.getByRole("button", { name: "Start run" }));
  expect(await sheet.findByText("This workflow needs it to know what to do.")).toBeDefined();
  expect(fetch.mock.calls.some(([r]) => r.method === "POST")).toBe(false);

  fireEvent.change(field, { target: { value: "Add rate limiting." } });
  fireEvent.click(sheet.getByRole("button", { name: "Start run" }));
  await waitFor(() => expect(navigate).toHaveBeenCalledWith(`/runs/${RUN_ID}`));
});
