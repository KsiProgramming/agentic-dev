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

/** A writer whose input port is typed (4.2): the run's prose input fails at that port before its
 * agent starts. (A typed output cannot fail on the stack: its fake agents fit what they answer to
 * the node's output schema, 6.8.) */
export const TYPED_READER = {
  ...WRITER,
  input_schema: {
    type: "object",
    required: ["findings"],
    properties: { findings: { type: "array" } },
  },
};

/** Run artifacts (4.3): a typed scanner writes `findings.json` (the fake runtime echoes the run's
 * JSON input), an unrelated step runs, then a gate, then a reporter that reads `findings.json`,
 * may look it up with the artifact tools, and writes `report.md`. */
export const ARTIFACTS = [
  { ...TYPED_WRITER, id: "scan", writes: "findings.json" },
  { type: "agent", id: "summary", role: "Editor", instructions: "Summarise your input." },
  { ...GATE, title: "Approve the findings" },
  {
    type: "agent",
    id: "report",
    role: "Writer",
    instructions: "Write a report of the findings in your input.",
    tools: ["artifacts.list", "artifacts.read"],
    reads: ["findings.json"],
    writes: "report.md",
  },
];

/** Deterministic scans (4.4) on the run's repo, each writing its findings report. */
export const SCANS = [
  { type: "tool", id: "lint", tool: "scan.lint", args: { linters: "auto" }, writes: "lint.json" },
  { type: "tool", id: "secrets", tool: "scan.secrets", writes: "secrets.json" },
];

export const FINDINGS_INPUT = '{"findings": [{"id": "F1", "severity": "high"}]}';

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

/** An evidence pack as a gate shows it (13.3): `failing` has a failed test and a new finding. */
export function evidencePack(failing: boolean) {
  const check = (kind: string, status: string, summary: string, detail = {}) => ({
    kind,
    status,
    required: true,
    summary,
    detail,
  });
  return {
    version: 1,
    gate: "approve",
    node: "writer",
    path: ".",
    rounds_left: failing ? 0 : 2,
    checks: failing
      ? [
          check("build", "passed", "1 module built"),
          check("tests", "failed", "tests failed (1 of 3)", {
            test_ms: 800,
            failures: [
              { name: "sum > adds", file: "src/sum.test.js", message: "expected 3 but got 4" },
            ],
          }),
          check("analyzers", "failed", "1 new finding", {
            findings: [
              { tool: "ruff", rule: "F401", path: "src/a.py", line: 3, message: "unused import" },
            ],
          }),
        ]
      : [
          check("build", "passed", "1 module built"),
          check("tests", "passed", "12 tests passed", { test_ms: 2500 }),
          check("analyzers", "passed", "no new findings"),
        ],
  };
}

/** An evidence pack with coverage and criteria (13.4): one criterion of each state, and changed
 * lines no test runs, so the review shows both lists next to the build, tests and analyzers. */
export function judgedEvidencePack() {
  const check = (kind: string, status: string, summary: string, detail = {}) => ({
    kind,
    status,
    required: true,
    summary,
    detail,
  });
  const pack = evidencePack(false);
  return {
    ...pack,
    rounds_left: 0,
    checks: [
      ...pack.checks,
      check("coverage", "failed", "50% of changed lines covered (5 of 10, needs 80%)", {
        changed: 10,
        covered: 5,
        percent: 50,
        threshold: 80,
        files: [
          {
            path: "src/sum.py",
            changed: 10,
            covered: 5,
            uncovered: [
              [7, 9],
              [12, 12],
            ],
          },
        ],
        truncated: false,
      }),
      check("criteria", "failed", "1 of 4 proven", {
        total: 4,
        proven: 1,
        criteria: [
          {
            id: "AC-001",
            state: "proven",
            tests: [{ name: "tests.test_sum::test_ac_001_adds", file: "tests/test_sum.py" }],
            before: "fails",
            after: "passes",
          },
          { id: "AC-002", state: "untested", tests: [], before: null, after: null },
          {
            id: "AC-003",
            state: "failing",
            tests: [{ name: "tests.test_sum::test_ac_003_zero", file: null }],
            before: null,
            after: "fails",
          },
          {
            id: "AC-004",
            state: "not_proven",
            tests: [{ name: "tests.test_sum::test_ac_004_keeps", file: null }],
            before: "passes",
            after: "passes",
          },
        ],
      }),
    ],
  };
}

/** Makes the gate of the page's run answer with `evidence` as well: the real gate, so the review
 * is the real one, plus the pack the stack's fake tools cannot produce. */
export async function withEvidence(
  page: import("@playwright/test").Page,
  evidence: ReturnType<typeof evidencePack>,
) {
  await page.route("**/runs/*/gate", async (route) => {
    const response = await route.fetch();
    if (!response.ok()) return route.fulfill({ response });
    const body = (await response.json()) as Record<string, unknown>;
    return route.fulfill({ response, json: { ...body, evidence } });
  });
}
