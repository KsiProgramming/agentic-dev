import { expect, test } from "vitest";

import { pendingGate, pullRequestUrl } from "./gates";
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
