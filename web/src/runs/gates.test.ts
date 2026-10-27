import { expect, test } from "vitest";

import {
  gateSummary,
  parseChanges,
  parseEdits,
  pendingGate,
  pullRequestUrl,
  SUMMARY_MAX,
  type PendingGate,
} from "./gates";
import { runEvent } from "./testing";

const WAITING = runEvent(2, "gate_waiting", {
  title: "Open a PR?",
  prompt: "Approving pushes.",
  artifact: "abc123 on agent/x/writer",
});

test("a gate waits until it is decided", () => {
  expect(pendingGate([runEvent(1, "run_started"), WAITING])).toEqual({
    nodeId: "summarizer",
    title: "Open a PR?",
    prompt: "Approving pushes.",
    artifact: "abc123 on agent/x/writer",
    changes: [],
    changesError: null,
    expiresAt: null,
  });
  expect(pendingGate([WAITING, runEvent(3, "gate_decided", { decision: "approve" })])).toBeNull();
  expect(pendingGate([runEvent(1, "run_started")])).toBeNull();
});

test("only GitHub pull request URLs are offered as links", () => {
  const opened = (url: string) => [runEvent(9, "pr_opened", { url, number: 1 })];

  expect(pullRequestUrl(opened("https://github.com/acme/api/pull/12"))).toBe(
    "https://github.com/acme/api/pull/12",
  );
  expect(pullRequestUrl(opened("javascript:alert(1)"))).toBeNull();
  expect(pullRequestUrl(opened("https://evil.test/acme/api/pull/1"))).toBeNull();
  expect(pullRequestUrl([])).toBeNull();
});

function gate(overrides: Partial<PendingGate>): PendingGate {
  return {
    nodeId: "g",
    title: "Approve?",
    prompt: null,
    artifact: "",
    changes: [],
    changesError: null,
    expiresAt: null,
    ...overrides,
  };
}

test("the dock summary is the prompt, else the artifact's first line of text", () => {
  expect(gateSummary(gate({ prompt: "  Approving pushes.  ", artifact: "x" }))).toBe(
    "Approving pushes.",
  );
  expect(
    gateSummary(gate({ artifact: "\n<!-- module: api -->\n\n## The api   module\nmore" })),
  ).toBe("The api module");
  expect(gateSummary(gate({ artifact: "- first item" }))).toBe("first item");
  expect(gateSummary(gate({ artifact: "<b></b>\n<i>bold</i> text" }))).toBe("bold text");
  expect(gateSummary(gate({}))).toBe("");
});

test("a long summary is cut at a word, within the limit", () => {
  const summary = gateSummary(gate({ prompt: "word ".repeat(60) }));

  expect(summary.length).toBeLessThanOrEqual(SUMMARY_MAX);
  expect(summary.endsWith("word…")).toBe(true);
});

const PAGE = {
  node_id: "writer",
  path: "docs/a.md",
  old_path: null,
  status: "added",
  editable: true,
  reason: null,
  before: null,
  after: "# A\n",
};

test("a gate shows the files its writers changed", () => {
  const waiting = runEvent(2, "gate_waiting", {
    title: "Open a PR?",
    changes: [PAGE, { ...PAGE, path: "logo.png", editable: false, reason: "binary", after: null }],
    changes_error: null,
  });

  expect(pendingGate([waiting])?.changes).toEqual([
    {
      nodeId: "writer",
      path: "docs/a.md",
      oldPath: null,
      status: "added",
      editable: true,
      reason: null,
      before: null,
      after: "# A\n",
    },
    {
      nodeId: "writer",
      path: "logo.png",
      oldPath: null,
      status: "added",
      editable: false,
      reason: "binary",
      before: null,
      after: null,
    },
  ]);
  const unreadable = runEvent(2, "gate_waiting", { changes: [], changes_error: "git failed" });
  expect(pendingGate([unreadable])?.changesError).toBe("git failed");
});

test("malformed changes are left out, and a file without its text is not editable", () => {
  expect(
    parseChanges([
      null,
      "docs/a.md",
      { ...PAGE, path: 3 },
      { ...PAGE, status: "exploded" },
      { ...PAGE, node_id: undefined },
      { ...PAGE, after: null },
      { ...PAGE, reason: "nonsense", editable: false },
    ]),
  ).toEqual([
    expect.objectContaining({ editable: false, reason: "binary", after: null }),
    expect.objectContaining({ editable: false, reason: "binary", before: null }),
  ]);
  expect(parseChanges({ not: "a list" })).toEqual([]);
});

test("a decision's edits are read, leaving out malformed ones", () => {
  expect(
    parseEdits([
      { node_id: "writer", path: "docs/a.md", content: "" },
      { node_id: "writer", path: "docs/b.md" },
      "x",
    ]),
  ).toEqual([{ nodeId: "writer", path: "docs/a.md", content: "" }]);
  expect(parseEdits(undefined)).toEqual([]);
});

test("a gate says when it expires, if it does", () => {
  const at = "2026-10-30T12:00:00+00:00";
  const expiring = runEvent(2, "gate_waiting", { title: "Go?", expires_at: at });
  const garbled = runEvent(2, "gate_waiting", { title: "Go?", expires_at: "soon" });

  expect(pendingGate([expiring])?.expiresAt).toBe(at);
  expect(pendingGate([garbled])?.expiresAt).toBeNull();
  expect(pendingGate([WAITING])?.expiresAt).toBeNull();
});
