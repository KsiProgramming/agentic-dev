import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { parseEvidence } from "../evidence";
import { EvidenceStrip } from "./evidence-strip";

function check(
  kind: string,
  status: string,
  summary: string,
  detail: Record<string, unknown> = {},
  required = true,
) {
  return { kind, status, required, summary, detail };
}

function pack(checks: unknown[], roundsLeft = 2) {
  return parseEvidence({
    version: 1,
    gate: "check",
    node: "writer",
    path: ".",
    checks,
    rounds_left: roundsLeft,
  });
}

const PASSING = pack([
  check("build", "passed", "1 module built"),
  check("tests", "passed", "12 tests passed", { test_ms: 2500 }),
  check("analyzers", "passed", "no new findings"),
]);

const FAILING = pack([
  check("build", "passed", "1 module built"),
  check("tests", "failed", "tests failed (1 of 3)", {
    test_ms: 800,
    failures: [{ name: "sum > adds", file: "src/sum.test.js", message: "expected 3 but got 4" }],
  }),
  check("analyzers", "failed", "1 new finding", {
    findings: [{ tool: "ruff", rule: "F401", path: "src/a.py", line: 3, message: "unused import" }],
  }),
]);

describe("EvidenceStrip", () => {
  it("shows each check with its outcome as a status badge", () => {
    render(<EvidenceStrip evidence={PASSING} />);

    const strip = screen.getByTestId("evidence");
    expect(within(strip).getAllByText("Passed")).toHaveLength(3);
    expect(within(strip).getByText("Build")).toBeTruthy();
    expect(within(strip).getByText("Tests")).toBeTruthy();
    expect(within(strip).getByText("Analyzers")).toBeTruthy();
    expect(within(strip).getByText(/12 tests passed/).textContent).toContain("2s");
    expect(screen.queryByRole("list", { name: "Failing tests" })).toBeNull();
  });

  it("names the failing tests and the new findings under the strip", () => {
    render(<EvidenceStrip evidence={FAILING} />);

    const tests = screen.getByRole("list", { name: "Failing tests" });
    expect(within(tests).getByText("sum > adds").className).toContain("font-mono");
    expect(within(tests).getByText("src/sum.test.js")).toBeTruthy();
    expect(within(tests).getByText("expected 3 but got 4")).toBeTruthy();
    const findings = screen.getByRole("list", { name: "New findings" });
    expect(within(findings).getByText("ruff F401")).toBeTruthy();
    expect(screen.getAllByText("Failed")).toHaveLength(2);
  });

  it("says the writer goes again while rounds are left, and that a person decides after", () => {
    const { rerender } = render(<EvidenceStrip evidence={FAILING} />);
    expect(screen.getByRole("status").textContent).toContain("The writer goes again.");

    rerender(<EvidenceStrip evidence={pack(FAILING ? failingChecks() : [], 0)} />);
    expect(screen.getByRole("status").textContent).toContain("you decide");
  });

  it("shows a skipped check as skipped, not as a failure", () => {
    render(
      <EvidenceStrip
        evidence={pack([
          check("build", "skipped", "nothing to build"),
          check("tests", "skipped", "no tests found"),
        ])}
      />,
    );

    expect(screen.getAllByText("Skipped")).toHaveLength(2);
    expect(screen.getByText("no tests found")).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("shows a check that could not run as its own outcome", () => {
    render(<EvidenceStrip evidence={pack([check("tests", "error", "test run timed out")])} />);

    expect(screen.getByText("Could not run")).toBeTruthy();
    expect(screen.getByText("test run timed out")).toBeTruthy();
  });

  it("has an empty state for a pack with no checks", () => {
    render(<EvidenceStrip evidence={pack([])} />);

    expect(screen.getByText("No checks ran for this change.")).toBeTruthy();
  });

  it("has a loading state and an error state with Retry", () => {
    const onRetry = vi.fn();
    const { rerender } = render(<EvidenceStrip evidence={null} loading />);
    expect(screen.getByRole("status").textContent).toBe("Loading the checks…");

    rerender(
      <EvidenceStrip evidence={null} error="Could not load the checks." onRetry={onRetry} />,
    );
    expect(screen.getByRole("alert").textContent).toContain("Could not load the checks.");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("renders nothing for a gate with no evidence", () => {
    const { container } = render(<EvidenceStrip evidence={null} />);

    expect(container.firstChild).toBeNull();
  });

  it("shows test names as text, never as markup", () => {
    render(
      <EvidenceStrip
        evidence={pack([
          check("tests", "failed", "tests failed (1 of 1)", {
            failures: [{ name: "<img src=x onerror=alert(1)>", message: "<b>bold</b>" }],
          }),
        ])}
      />,
    );

    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeTruthy();
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("b")).toBeNull();
  });
});

function failingChecks() {
  return [check("tests", "failed", "tests failed (1 of 3)")];
}

describe("parseEvidence", () => {
  it("is null for anything that is not a pack", () => {
    expect(parseEvidence(null)).toBeNull();
    expect(parseEvidence({ checks: "x" })).toBeNull();
    expect(parseEvidence([])).toBeNull();
  });

  it("leaves out malformed checks and reads rounds_left", () => {
    const found = pack(
      [check("build", "passed", "ok"), { kind: "nope" }, check("tests", "weird", "")],
      1,
    );

    expect(found?.checks.map((c) => c.kind)).toEqual(["build"]);
    expect(found?.roundsLeft).toBe(1);
  });
});
