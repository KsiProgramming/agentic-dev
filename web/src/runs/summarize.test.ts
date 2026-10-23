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
  ["tool_call", { name: "list_files", arguments: { path: "." } }, 'list_files({"path":"."})'],
  ["tool_result", { output: "README.md" }, "README.md"],
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
  ["something_new", { a: 1 }, '{"a":1}'],
])("%s → one line of text", (type, payload, expected) => {
  expect(summarizePayload(runEvent(1, type, payload))).toBe(expected);
});

test("long payloads are truncated", () => {
  const summary = summarizePayload(runEvent(1, "text_delta", { text: "x".repeat(500) }));

  expect(summary).toHaveLength(200);
  expect(summary.endsWith("…")).toBe(true);
});
