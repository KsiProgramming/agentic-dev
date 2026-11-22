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

const CRITERIA = [
  {
    id: "AC-001",
    state: "proven",
    tests: [{ name: "tests.test_export::test_ac_001_exports", file: "tests/test_export.py" }],
    before: "fails",
    after: "passes",
  },
  { id: "AC-002", state: "untested", tests: [], before: null, after: null },
  {
    id: "AC-003",
    state: "failing",
    tests: [{ name: "test_ac_003_rejects", file: null }],
    before: null,
    after: "fails",
  },
  {
    id: "AC-004",
    state: "not_proven",
    tests: [{ name: "test_ac_004_keeps", file: null }],
    before: "passes",
    after: "passes",
  },
  { id: "AC-005", state: "unchecked", tests: [], before: null, after: null },
];

describe("EvidenceStrip: coverage and criteria", () => {
  it("shows the share of changed lines the tests ran, the counts and the threshold", () => {
    render(
      <EvidenceStrip
        evidence={pack([
          check("coverage", "passed", "100% of changed lines covered", {
            changed: 10,
            covered: 9,
            percent: 90,
            threshold: 80,
            files: [{ path: "src/sum.py", changed: 10, covered: 9, uncovered: [[7, 7]] }],
            truncated: false,
          }),
        ])}
      />,
    );

    const strip = screen.getByTestId("evidence");
    expect(within(strip).getByText("Coverage")).toBeTruthy();
    expect(within(strip).getByText("90%")).toBeTruthy();
    expect(within(strip).getByText("Passed")).toBeTruthy();
    expect(within(strip).getByText("9 of 10 changed lines · needs 80%")).toBeTruthy();
    const lines = screen.getByRole("list", { name: "Uncovered lines" });
    expect(within(lines).getByText("no test runs lines 7")).toBeTruthy();
  });

  it("lists the uncovered ranges of a failing coverage check and says the writer goes again", () => {
    render(
      <EvidenceStrip
        evidence={pack([
          check("coverage", "failed", "50% of changed lines covered", {
            changed: 10,
            covered: 5,
            percent: 50,
            threshold: 80,
            files: [
              {
                path: "src/sum.py",
                changed: 10,
                covered: 5,
                uncovered: [
                  [7, 9],
                  [12, 12],
                ],
              },
            ],
            truncated: false,
          }),
        ])}
      />,
    );

    expect(screen.getByText("50%")).toBeTruthy();
    expect(screen.getByText("Failed")).toBeTruthy();
    expect(screen.getByText("no test runs lines 7-9, 12")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("Coverage failed");
  });

  it("shows no figure for a change with no executable lines", () => {
    render(
      <EvidenceStrip
        evidence={pack([
          check("coverage", "passed", "no changed lines to cover", {
            changed: 0,
            covered: 0,
            percent: 100,
            threshold: 80,
            files: [],
            truncated: false,
          }),
        ])}
      />,
    );

    expect(screen.getByText("no changed lines to cover")).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Uncovered lines" })).toBeNull();
    expect(screen.queryByText("100%")).toBeNull();
  });

  it("shows how many criteria are proven and each one's state, tests and before and after", () => {
    render(
      <EvidenceStrip
        evidence={pack([
          check("criteria", "failed", "1 of 5 proven", { total: 5, proven: 1, criteria: CRITERIA }),
        ])}
      />,
    );

    expect(screen.getByText("1 of 5")).toBeTruthy();
    const list = screen.getByRole("list", { name: "Acceptance criteria" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(5);
    expect(within(rows[0]).getByText("AC-001").className).toContain("font-mono");
    expect(within(rows[0]).getByText("Proven")).toBeTruthy();
    expect(within(rows[0]).getByText("fails before → passes after")).toBeTruthy();
    expect(within(rows[0]).getByText("tests.test_export::test_ac_001_exports")).toBeTruthy();
    expect(within(rows[1]).getByText("Untested")).toBeTruthy();
    expect(within(rows[2]).getByText("Failing")).toBeTruthy();
    expect(within(rows[2]).getByText("fails after")).toBeTruthy();
    expect(within(rows[3]).getByText("Not proven")).toBeTruthy();
    expect(within(rows[3]).getByText("passes before → passes after")).toBeTruthy();
    expect(within(rows[4]).getByText("Not checked")).toBeTruthy();
  });

  it("lists at most eight criteria and then says how many more", () => {
    const many = Array.from({ length: 11 }, (_, i) => ({
      id: `AC-${String(i + 1).padStart(3, "0")}`,
      state: "proven",
      tests: [],
      before: "fails",
      after: "passes",
    }));
    render(
      <EvidenceStrip
        evidence={pack([
          check("criteria", "passed", "11 of 11 proven", { total: 11, proven: 11, criteria: many }),
        ])}
      />,
    );

    const list = screen.getByRole("list", { name: "Acceptance criteria" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(9);
    expect(within(list).getByText("and 3 more")).toBeTruthy();
  });

  it("says why a Node module is not measured, as a check that could not run", () => {
    render(
      <EvidenceStrip
        evidence={pack([
          check("coverage", "error", "coverage is not measured for node yet"),
          check("criteria", "error", "0 of 1 proven, 1 could not be checked", {
            total: 1,
            proven: 0,
            criteria: [{ id: "AC-001", state: "unchecked", tests: [], before: null, after: null }],
          }),
        ])}
      />,
    );

    expect(screen.getAllByText("Could not run")).toHaveLength(2);
    expect(screen.getByText("coverage is not measured for node yet")).toBeTruthy();
    expect(screen.getByText("Not checked")).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull(); // not the writer's failure: no send-back line
  });

  it("keeps build, tests and analyzers in their own strip beside coverage and criteria", () => {
    render(
      <EvidenceStrip
        evidence={pack([
          check("build", "passed", "1 module built"),
          check("tests", "passed", "3 tests passed"),
          check("analyzers", "passed", "no findings"),
          check("coverage", "passed", "no changed lines to cover", { changed: 0, covered: 0 }),
          check("criteria", "skipped", "no acceptance criteria listed"),
        ])}
      />,
    );

    expect(document.querySelectorAll('[data-slot="stat-strip"]')).toHaveLength(2);
    expect(screen.getByText("no acceptance criteria listed")).toBeTruthy();
  });

  it("shows criteria and test names as text, never as markup", () => {
    render(
      <EvidenceStrip
        evidence={pack([
          check("criteria", "failed", "0 of 1 proven", {
            criteria: [
              {
                id: "AC-001",
                state: "failing",
                tests: [{ name: "<img src=x onerror=alert(1)>", file: null }],
                before: null,
                after: "fails",
              },
            ],
          }),
        ])}
      />,
    );

    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeTruthy();
    expect(document.querySelector("img")).toBeNull();
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
