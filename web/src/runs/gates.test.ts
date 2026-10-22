import { expect, test } from "vitest";

import { gateSummary, pendingGate, pullRequestUrl, SUMMARY_MAX, type PendingGate } from "./gates";
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
  return { nodeId: "g", title: "Approve?", prompt: null, artifact: "", ...overrides };
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
