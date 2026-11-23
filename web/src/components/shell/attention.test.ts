import { expect, test } from "vitest";

import { attentionTitle } from "./attention";

test("the console of a waiting run puts Needs approval in front of the title", () => {
  expect(attentionTitle("Run · Agentic", 0, true)).toBe("● Needs approval · Run · Agentic");
});

test("the console of a run a circuit breaker paused puts Paused in front", () => {
  expect(attentionTitle("Run · Agentic", 0, true, true)).toBe("● Paused · Run · Agentic");
  // A prefix of either kind is replaced, never stacked.
  expect(attentionTitle("● Paused · Run · Agentic", 0, true)).toBe(
    "● Needs approval · Run · Agentic",
  );
  expect(attentionTitle("● Needs approval · Run · Agentic", 0, false)).toBe("Run · Agentic");
});
