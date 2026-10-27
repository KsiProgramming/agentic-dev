import { expect, test } from "vitest";

import { summarizePayload } from "./summarize";
import { runEvent } from "./testing";

test.each([
  ["text_delta", { text: "Hello" }, "Hello"],
  ["message", { text: "Done." }, "Done."],
  ["usage", { input_tokens: 12, output_tokens: 34 }, "12 in / 34 out tokens"],
  [
    "usage",
    { input_tokens: 1, output_tokens: 2, estimated_usd: 0.00125 },
    "1 in / 2 out tokens, ~$0.0013",
  ],
  ["run_failed", { error: "RuntimeError: boom" }, "RuntimeError: boom"],
  ["tool_call", { name: "repo.read_file", arguments: { path: "a.ts" } }, "Read a.ts"],
  ["tool_call", { name: "lint", arguments: { path: "." } }, "Called lint ."],
  ["tool_result", { output: "README.md" }, "README.md"],
  ["tool_result", { output: '{"modules": ["a", "b"]}' }, "JSON, 1 entry"],
  ["node_completed", {}, ""],
  [
    "policy_limit_exceeded",
    { limit: "agents_spawned", value: 40, observed: 41 },
    "agents spawned: 41, limit 40",
  ],
  [
    "policy_limit_exceeded",
    { limit: "wall_time_s", value: 7200, observed: 7201 },
    "wall time: limit 2h 0m",
  ],
  [
    "policy_limit_exceeded",
    { limit: "budget_usd", value: "1", observed: "1.2" },
    "budget: $1.20 spent, limit $1.00",
  ],
  [
    "policy_limit_exceeded",
    { limit: "budget_usd", value: "1", observed: "0", model: "m" },
    "budget: no price for m, limit $1.00",
  ],
  ["something_new", { a: 1, b: { c: 2 }, d: [1, 2] }, "a: 1 · b: 1 entry · d: 2 entries"],
])("%s → one line of text", (type, payload, expected) => {
  expect(summarizePayload(runEvent(1, type, payload))).toBe(expected);
});

test("long payloads are truncated", () => {
  const summary = summarizePayload(runEvent(1, "text_delta", { text: "x".repeat(500) }));

  expect(summary).toHaveLength(200);
  expect(summary.endsWith("…")).toBe(true);
});
