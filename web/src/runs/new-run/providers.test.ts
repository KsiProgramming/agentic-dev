import { expect, test } from "vitest";

import type { WorkflowSpec } from "@/runs/graph/spec-graph";

import { defaultChoice, pinnedAway, requiredFor, resolveRun, type RunProvider } from "./providers";

const agent = (id: string, provider?: RunProvider) => ({
  type: "agent" as const,
  id,
  role: "R",
  instructions: "Go.",
  ...(provider ? { provider } : {}),
});

function spec(steps: unknown[], provider?: RunProvider): WorkflowSpec {
  return {
    spec_version: "0",
    id: "w",
    name: "W",
    ...(provider ? { provider } : {}),
    root: { type: "sequence", id: "seq", steps },
  } as unknown as WorkflowSpec;
}

test("the choice is the workflow's provider, else the workspace's, else Claude", () => {
  expect(defaultChoice(spec([], "copilot"), "claude")).toBe("copilot");
  expect(defaultChoice(spec([]), "copilot")).toBe("copilot");
  expect(defaultChoice(spec([]), null)).toBe("claude");
  expect(defaultChoice(null, undefined)).toBe("claude");
});

test("every agent follows the run's choice unless it names its own", () => {
  const s = spec([agent("builder"), agent("reviewer", "copilot")]);

  expect(resolveRun(s, "claude").agents).toEqual([
    { id: "builder", provider: "claude", pinned: false },
    { id: "reviewer", provider: "copilot", pinned: true },
  ]);
  expect(resolveRun(s, "copilot").agents.map((a) => a.provider)).toEqual(["copilot", "copilot"]);
});

test("a hub, a classifier and a reduce agent count as agents", () => {
  const s = spec([
    {
      type: "orchestrator",
      id: "team",
      hub: { role: "Lead", instructions: "Plan.", provider: "claude" },
      body: agent("worker"),
    },
    {
      type: "reduce",
      id: "sum",
      from: "team",
      strategy: "agent",
      agent: { role: "S", instructions: "Sum." },
    },
    { type: "reduce", id: "join", from: "team", strategy: "concat" },
    { type: "router", id: "pick", classifier: { instructions: "Choose." }, routes: [] },
  ]);

  expect(resolveRun(s, "copilot").agents).toEqual([
    { id: "team", provider: "claude", pinned: true },
    { id: "worker", provider: "copilot", pinned: false },
    { id: "sum", provider: "copilot", pinned: false },
    { id: "pick", provider: "copilot", pinned: false },
  ]);
});

test("Claude-only: no personal account, Claude still required", () => {
  const resolved = resolveRun(spec([agent("a")]), "claude");

  expect(resolved.uses).toEqual({ claude: true, copilot: false });
  expect(requiredFor(["claude", "github"], resolved)).toEqual(["claude", "github"]);
});

test("Copilot-only: no Claude key is asked for", () => {
  const resolved = resolveRun(spec([agent("a"), agent("b")]), "copilot");

  expect(resolved.uses).toEqual({ claude: false, copilot: true });
  expect(requiredFor(["claude", "github"], resolved)).toEqual(["github"]);
});

test("mixed: both are needed, and a pinned node is named when it is not on the choice", () => {
  const resolved = resolveRun(spec([agent("builder"), agent("reviewer", "copilot")]), "claude");

  expect(resolved.uses).toEqual({ claude: true, copilot: true });
  expect(requiredFor(["claude"], resolved)).toEqual(["claude"]);
  expect(pinnedAway(resolved, "claude").map((a) => a.id)).toEqual(["reviewer"]);
});

test("a pinned Claude node keeps the key when the choice is Copilot", () => {
  const resolved = resolveRun(spec([agent("builder", "claude"), agent("reviewer")]), "copilot");

  expect(requiredFor(["claude"], resolved)).toEqual(["claude"]);
  expect(pinnedAway(resolved, "copilot").map((a) => a.id)).toEqual(["builder"]);
});

test("with no spec (a template) the choice stands for every agent", () => {
  expect(resolveRun(null, "copilot").uses).toEqual({ claude: false, copilot: true });
  expect(resolveRun(null, "claude").uses).toEqual({ claude: true, copilot: false });
});
