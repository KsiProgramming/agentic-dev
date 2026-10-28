import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { stepEntries, stepRows } from "../console/step-entries";
import { StepOutput } from "../console/step-output";
import { describeTool } from "../console/tool-describe";
import { runEvent } from "../testing";
import { buildTimeline } from "../timeline";
import { checkLine, isFindingsReport, sortFindings, type Finding } from "./findings";
import { FINDINGS_SHOWN, FindingsView } from "./findings-view";

function finding(overrides: Partial<Finding> = {}): Finding {
  return {
    fingerprint: `fp-${Math.random()}`,
    tool: "ruff",
    rule: "F401",
    severity: "medium",
    category: "lint",
    path: "api/app.py",
    line: 1,
    message: "`os` imported but unused",
    help_url: "https://docs.astral.sh/ruff/rules/unused-import",
    config: "repo",
    ...overrides,
  };
}

const LINT = {
  scanner: "lint" as const,
  checks: [
    { path: "api", kind: "python", tool: "ruff", config: "repo" as const, status: "ran" as const },
    {
      path: "legacy",
      kind: "node",
      tool: "eslint",
      status: "skipped" as const,
      reason: "eslint is not supported",
    },
  ],
  findings: [
    finding({ fingerprint: "a", severity: "low", path: "b.py" }),
    finding({ fingerprint: "b", severity: "critical", path: "z.py", line: 9 }),
    finding({ fingerprint: "c", severity: "critical", path: "a.py", line: 3 }),
  ],
  counts: { critical: 2, high: 0, medium: 0, low: 1, info: 0 },
  truncated: false,
};

describe("findings reports", () => {
  it("recognises a report and nothing else", () => {
    expect(isFindingsReport(LINT)).toBe(true);
    expect(isFindingsReport({ ...LINT, scanner: "other" })).toBe(false);
    expect(isFindingsReport({ ...LINT, findings: [{ rule: "x" }] })).toBe(false);
    expect(isFindingsReport({ modules: [] })).toBe(false);
    expect(isFindingsReport(null)).toBe(false);
  });

  it("sorts most severe first, then by file and line", () => {
    expect(sortFindings(LINT.findings).map((f) => f.fingerprint)).toEqual(["c", "b", "a"]);
  });

  it("says what each check did, and why one did not run", () => {
    expect(LINT.checks.map(checkLine)).toEqual([
      "ruff · repo config",
      "skipped: eslint is not supported",
    ]);
  });

  it("describes the scan tools", () => {
    expect(describeTool("scan.lint", { linters: "auto", path: "." })).toMatchObject({
      done: "Linted",
      target: "the repository",
    });
    expect(describeTool("scan.lint", { linters: ["ruff", "biome"], path: "api" })).toMatchObject({
      done: "Linted with ruff, biome",
      target: "api",
    });
    expect(describeTool("scan.secrets", {}).doing).toBe("Scanning for secrets in");
    expect(describeTool("scan.dependencies", { path: "web" }).target).toBe("web");
  });
});

describe("FindingsView", () => {
  it("shows counts, what was checked and the findings with severity as icon and word", () => {
    render(<FindingsView report={LINT} label="Findings of lint" />);

    const view = screen.getByTestId("findings-view");
    expect(within(view).getAllByText("Critical").length).toBeGreaterThan(0);
    const checks = screen.getAllByTestId("scan-check");
    expect(checks.map((c) => c.getAttribute("data-status"))).toEqual(["ran", "skipped"]);
    expect(checks[1]?.textContent).toContain("eslint is not supported");
    const table = screen.getByRole("table", { name: "Findings of lint" });
    const rows = within(table).getAllByTestId("finding-row");
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining("a.py:3"),
      expect.stringContaining("z.py:9"),
      expect.stringContaining("b.py:1"),
    ]);
    const badge = rows[0]!.querySelector("[data-severity]")!;
    expect(badge.textContent).toBe("Critical");
    expect(badge.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
    // Severity is not a status: no status colour on it.
    expect(badge.getAttribute("data-variant")).toBe("outline");
    expect(badge.className).not.toMatch(/status-/);
    const link = within(rows[0]!).getByRole("link", { name: /F401/ });
    expect(link.getAttribute("href")).toBe("https://docs.astral.sh/ruff/rules/unused-import");
    // The same findings as cards for small screens.
    expect(screen.getAllByTestId("finding-card")).toHaveLength(3);
  });

  it("shows the first rows, then all of them on request", () => {
    const many = Array.from({ length: FINDINGS_SHOWN + 5 }, (_, i) =>
      finding({ fingerprint: `f${i}`, line: i + 1 }),
    );
    render(
      <FindingsView
        report={{ ...LINT, findings: many, counts: { medium: many.length } }}
        label="Findings"
      />,
    );

    expect(screen.getAllByTestId("finding-row")).toHaveLength(FINDINGS_SHOWN);
    fireEvent.click(screen.getByRole("button", { name: `Show all ${FINDINGS_SHOWN + 5}` }));
    expect(screen.getAllByTestId("finding-row")).toHaveLength(FINDINGS_SHOWN + 5);
  });

  it("says when there is nothing to report, and when the list was cut", () => {
    const { unmount } = render(
      <FindingsView report={{ ...LINT, findings: [], counts: {} }} label="Findings" />,
    );
    expect(screen.getByText("Lint: no findings.")).toBeTruthy();
    unmount();

    render(<FindingsView report={{ ...LINT, truncated: true }} label="Findings" />);
    expect(screen.getByText(/Showing the 3 most severe of 3 findings/)).toBeTruthy();
  });

  it("shows a dependency's fix and aliases, and marks platform-default rules", () => {
    const report = {
      ...LINT,
      scanner: "dependencies" as const,
      findings: [
        finding({
          fingerprint: "d",
          tool: "osv-scanner",
          rule: "GHSA-462w-v97r-4m45",
          category: "dependency",
          severity: "high",
          line: null,
          config: null,
          fixed_versions: ["2.10.1"],
          aliases: ["CVE-2019-10906"],
        }),
        finding({ fingerprint: "e", config: "platform-default" }),
      ],
    };
    render(<FindingsView report={report} label="Findings" />);

    const [dep, lint] = screen.getAllByTestId("finding-row");
    expect(dep!.textContent).toContain("Fixed in 2.10.1 · CVE-2019-10906");
    expect(lint!.textContent).toContain("Platform default rules");
  });
});

describe("a scan step's output", () => {
  it("shows its report as findings, not raw JSON", () => {
    const events = [
      runEvent(1, "node_started"),
      runEvent(2, "tool_call", { call_id: "c", name: "scan.lint", arguments: { linters: "auto" } }),
      runEvent(3, "tool_result", { call_id: "c", output: JSON.stringify(LINT) }),
      runEvent(4, "node_completed"),
    ].map((e) => ({ ...e, node_id: "lint" }));
    const entries = stepEntries(buildTimeline(events).steps);
    const [row] = stepRows(entries);
    if (!row) throw new Error("no row");

    render(
      <StepOutput
        runId="run-1"
        step={row.step}
        row={row}
        kind="tool"
        entries={entries}
        onSelect={() => undefined}
      />,
    );

    expect(screen.getByTestId("findings-view")).toBeTruthy();
    expect(screen.getByRole("table", { name: "Findings of lint" })).toBeTruthy();
  });
});
