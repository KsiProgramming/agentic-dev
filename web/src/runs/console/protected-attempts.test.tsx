import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import {
  attemptsFromEvents,
  parseChanges,
  parseProtectedAttempts,
  type ProtectedAttempt,
} from "../gates";
import type { RunEvent } from "../types";
import { ProtectedAttempts, ProtectedPathsList } from "./protected-attempts";

const ATTEMPTS: ProtectedAttempt[] = [
  { nodeId: "implementer", path: "tests/test_cart.py", rule: "frozen", count: 2 },
  { nodeId: "implementer", path: ".github/workflows/ci.yml", rule: "default", count: 1 },
];

test("lists each attempt with its path, writer, count and the rule that refused it", () => {
  render(<ProtectedAttempts attempts={ATTEMPTS} />);

  const region = screen.getByTestId("protected-attempts");
  expect(region.textContent).toContain("Protected files: 3 changes were refused");
  expect(region.textContent).toContain("tests/test_cart.py");
  expect(region.textContent).toContain("implementer · 2 times");
  expect(region.textContent).toContain("Approved tests");
  expect(region.textContent).toContain("Platform: CI and analyzer config");
});

test("a review with no attempts shows nothing", () => {
  const { container } = render(<ProtectedAttempts attempts={[]} />);

  expect(container.innerHTML).toBe("");
});

test("it has a loading state and an error state with Retry", () => {
  const onRetry = vi.fn();
  const { rerender } = render(<ProtectedAttempts attempts={[]} loading />);
  expect(screen.getByText("Loading the attempts…")).toBeTruthy();

  rerender(<ProtectedAttempts attempts={[]} error="Could not read them." onRetry={onRetry} />);
  fireEvent.click(screen.getByRole("button", { name: /retry/i }));

  expect(screen.getByText("Could not read them.")).toBeTruthy();
  expect(onRetry).toHaveBeenCalled();
});

test("a path is shown as text, never as markup", () => {
  render(
    <ProtectedAttempts
      attempts={[
        { nodeId: "w", path: "<img src=x onerror=alert(1)>.py", rule: "workflow", count: 1 },
      ]}
    />,
  );

  expect(screen.getByTestId("protected-attempts").querySelector("img")).toBeNull();
});

test("the API's attempts are read, and malformed ones left out", () => {
  expect(
    parseProtectedAttempts([
      { node_id: "w", path: "a.py", rule: "frozen", count: 3 },
      { node_id: "w", path: "b.py", rule: "other", count: 1 },
      { node_id: "w", path: "c.py", rule: "default", count: 0 },
      "nonsense",
    ]),
  ).toEqual([{ nodeId: "w", path: "a.py", rule: "frozen", count: 3 }]);
  expect(parseProtectedAttempts(undefined)).toEqual([]);
});

function refused(seq: number, nodeId: string, path: string, kind: string): RunEvent {
  return {
    run_id: "r",
    seq,
    type: "protected_path_refused",
    node_id: nodeId,
    payload: { tool: "repo.write_file", path, rule: { kind } },
    created_at: "2026-11-23T10:00:00Z",
  };
}

test("the console groups a run's refusals by writer, path and rule, the most tried first", () => {
  const events = [
    refused(1, "impl", "a.py", "frozen"),
    refused(2, "impl", "b.py", "default"),
    refused(3, "impl", "b.py", "default"),
    refused(4, "impl", "x.py", "nonsense"),
  ];

  expect(attemptsFromEvents(events)).toEqual([
    { nodeId: "impl", path: "b.py", rule: "default", count: 2 },
    { nodeId: "impl", path: "a.py", rule: "frozen", count: 1 },
  ]);
});

test("a protected file in a gate's changes carries its rule", () => {
  const [plain, marked] = parseChanges([
    { node_id: "w", path: "src/a.py", status: "added", editable: false, reason: "binary" },
    {
      node_id: "w",
      path: "tests/t.py",
      status: "added",
      editable: false,
      reason: "binary",
      protected: true,
      rule: "frozen",
    },
  ]);

  expect(plain?.protected).toBeNull();
  expect(marked?.protected).toBe("frozen");
});

test("the Input tab lists a step's patterns and the files frozen at a gate", () => {
  render(
    <ProtectedPathsList
      paths={{
        patterns: [".github/workflows/**", "**/conftest.py"],
        frozen: ["tests/test_cart.py"],
        frozenFrom: "test_writer",
        gate: "approve_tests",
      }}
    />,
  );

  const list = screen.getByTestId("protected-paths");
  expect(list.textContent).toContain("**/conftest.py");
  expect(list.textContent).toContain(
    "Approved at approve_tests from test_writer, on its branch already:",
  );
  expect(list.textContent).toContain("tests/test_cart.py");
});
