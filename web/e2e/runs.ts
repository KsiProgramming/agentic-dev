import { expect, type APIRequestContext } from "@playwright/test";

import { apiURL, e2eWorkspaceId } from "./workspace";

export { apiURL };

/** The fake GitHub App's repo (`AGENTIC_GITHUB=fake`), as a run names it. */
export const DOCS_DEMO_URL = "https://github.com/e2e-org/docs-demo";

/** Starts a run of `steps` in a sequence through the API, in the E2E workspace, and returns its
 * id. With `repo`, the run works on that repo in a sandbox. */
export async function startRun(
  request: APIRequestContext,
  steps: unknown[],
  name = "E2E layout",
  repo?: string,
  input = "hello",
): Promise<string> {
  const response = await request.post(`${apiURL}/runs`, {
    data: {
      workflow: {
        spec_version: "0",
        id: "e2e-layout",
        name,
        root: { type: "sequence", id: "main", steps },
      },
      input,
      workspace_id: e2eWorkspaceId(),
      ...(repo ? { repo: { url: repo } } : {}),
    },
  });
  expect(response.status()).toBe(202);
  return ((await response.json()) as { run_id: string }).run_id;
}

export const WRITER = { type: "agent", id: "writer", role: "Writer", instructions: "Say hello." };

export const GATE = {
  type: "gate",
  id: "approve",
  title: "Approve the greeting",
  prompt: "Check it before the run ends.",
};

/** A writer whose output must be JSON with a `findings` list (4.2). The fake runtime echoes its
 * input, so it fails at its output port on "hello" and passes on `{"findings": []}`. */
export const TYPED_WRITER = {
  ...WRITER,
  output_schema: {
    type: "object",
    required: ["findings"],
    properties: { findings: { type: "array" } },
  },
};

/** A gate that expires a few seconds after it pauses (the e2e worker sweeps every second). */
export const EXPIRING_GATE = { ...GATE, ttl_s: 8 };

/** A loop whose `until` is not a bool: it fails after its first round, and so does the run. */
export const FAILING = {
  type: "loop",
  id: "broken",
  body: { type: "agent", id: "draft", role: "Writer", instructions: "Say hello." },
  until: "iteration",
  max_iterations: 2,
};

/** A map over two items, each written by an agent, then combined: containers on the graph. */
export const MAP = {
  type: "map",
  id: "each",
  over: '["alpha", "beta"]',
  max_concurrency: 2,
  body: { type: "agent", id: "worker", role: "Writer", instructions: "Say hello." },
};

export const COMBINE = { type: "reduce", id: "combine", from: "each", strategy: "concat" };

/** A writer on the run's repo: the fake runtime calls each tool once, so it writes and commits
 * `NOTES.md` (the `repo.write_file` example). */
export const REPO_WRITER = {
  type: "agent",
  id: "writer",
  role: "Writer",
  instructions: "Write NOTES.md and commit it.",
  tools: ["repo.write_file", "repo.commit"],
};

/** A reader on the run's repo: the fake runtime reasons, then calls each tool once with its
 * example arguments, intent included ("See how the repo is laid out"), then answers. */
export const REPO_READER = {
  type: "agent",
  id: "reader",
  role: "Reader",
  instructions: "Look around the repository.",
  tools: ["repo.list_files", "repo.read_file", "repo.search"],
};

/** A gate after `REPO_WRITER`: it shows the files the writer changed. */
export const REVIEW_GATE = {
  type: "gate",
  id: "approve",
  title: "Open a pull request with the notes?",
  prompt: "Approving pushes the writer's branch and opens a pull request.",
};

/** Opens a pull request from `REPO_WRITER`'s branch (the fake GitHub App answers). */
export const PUBLISH = {
  type: "tool",
  id: "publish",
  tool: "github.openPR",
  args: { from_node: "writer", title: "Add notes", body: "Written by an agent." },
};

/** Starts writer → gate → pull request on the fixture repo; it pauses with `NOTES.md` to review. */
export function startReviewRun(request: APIRequestContext, name = "E2E review"): Promise<string> {
  return startRun(request, [REPO_WRITER, REVIEW_GATE, PUBLISH], name, DOCS_DEMO_URL);
}

/** The run's events, read once it has ended (its stream closes after the final event). */
export async function endedRunEvents(
  request: APIRequestContext,
  runId: string,
): Promise<{ type: string; node_id: string | null; payload: Record<string, unknown> }[]> {
  const response = await request.get(`${apiURL}/runs/${runId}/events`);
  expect(response.status()).toBe(200);
  return (await response.text())
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => JSON.parse(line.slice("data:".length)));
}
