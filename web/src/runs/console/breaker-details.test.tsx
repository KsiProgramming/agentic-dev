import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";

import { parseBreaker, type BreakerTrip } from "../breaker";
import { BreakerDetails } from "./breaker-details";

function trip(overrides: Record<string, unknown>): BreakerTrip {
  const parsed = parseBreaker({
    breaker: "repeat",
    trigger: "calls",
    threshold: 5,
    observed: 5,
    details: {},
    reason: "A reason.",
    ...overrides,
  });
  if (!parsed) throw new Error("not a trip");
  return parsed;
}

function wrap(value: BreakerTrip | null, props: Record<string, unknown> = {}) {
  return (
    <TooltipProvider>
      <BreakerDetails trip={value} {...props} />
    </TooltipProvider>
  );
}

test("a repeat of failing calls names the tool, the call and the error", () => {
  render(
    wrap(
      trip({
        trigger: "errors",
        threshold: 3,
        observed: 3,
        details: {
          tool: "repo.read_file",
          arguments: { path: "docs/gone.md" },
          error: "no such file: docs/gone.md",
        },
        reason: "repo.read_file failed 3 times with the same error in one step",
      }),
    ),
  );

  const text = screen.getByTestId("breaker-details").textContent ?? "";
  expect(text).toContain("Repeat breaker");
  expect(text).toContain("repo.read_file failed 3 times");
  expect(text).toContain("3 errors, reached 3");
  expect(text).toContain("docs/gone.md");
  expect(text).toContain("no such file");
});

test("a cost trip shows the cost against the node's average", () => {
  render(
    wrap(
      trip({
        breaker: "cost",
        trigger: "cost",
        threshold: 3,
        observed: 4.2,
        details: { spent_usd: 2.1, average_usd: 0.5 },
      }),
    ),
  );

  const text = screen.getByTestId("breaker-details").textContent ?? "";
  expect(text).toContain("Cost breaker");
  expect(text).toContain("$2.10");
  expect(text).toContain("average of $0.5");
});

test("a paths trip shows the path and the declared globs", () => {
  render(
    wrap(
      trip({
        breaker: "paths",
        trigger: "write",
        details: { tool: "repo.write_file", path: "README.md", declared: ["docs/**"] },
      }),
    ),
  );

  const text = screen.getByTestId("breaker-details").textContent ?? "";
  expect(text).toContain("Paths breaker");
  expect(text).toContain("README.md");
  expect(text).toContain("docs/**");
});

test("a flip-flop trip shows the file and its flips", () => {
  render(
    wrap(
      trip({
        breaker: "flip_flop",
        trigger: "flips",
        threshold: 2,
        observed: 2,
        details: { path: "src/app.py", flips: 2 },
      }),
    ),
  );

  const text = screen.getByTestId("breaker-details").textContent ?? "";
  expect(text).toContain("Flip-flop breaker");
  expect(text).toContain("src/app.py");
  expect(text).toContain("2 flips");
});

test("what it saw is text, never markup, and a long error is clamped", () => {
  render(
    wrap(
      trip({
        trigger: "errors",
        details: { tool: "repo.read_file", error: "<img src=x onerror=alert(1)>" },
      }),
    ),
  );

  const region = screen.getByTestId("breaker-details");
  expect(region.querySelector("img")).toBeNull();
  expect(region.textContent).toContain("<img src=x onerror=alert(1)>");
  expect(region.querySelector(".line-clamp-2")).not.toBeNull();
});

test("it has a loading state, an error state with Retry and an empty state", () => {
  const onRetry = vi.fn();
  const { rerender } = render(wrap(null, { loading: true }));
  expect(screen.getByText("Loading the pause…")).toBeTruthy();

  rerender(wrap(null, { error: "Could not load it.", onRetry }));
  fireEvent.click(screen.getByRole("button", { name: /retry/i }));
  expect(onRetry).toHaveBeenCalled();

  rerender(wrap(null));
  expect(screen.getByText("No circuit breaker paused this step.")).toBeTruthy();
});

test("a payload of another shape is not a trip", () => {
  expect(parseBreaker(null)).toBeNull();
  expect(parseBreaker({ breaker: "nope", threshold: 1, observed: 1 })).toBeNull();
  expect(parseBreaker({ breaker: "repeat", threshold: "3", observed: 3 })).toBeNull();
});
