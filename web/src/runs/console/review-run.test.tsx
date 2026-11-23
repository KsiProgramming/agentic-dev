import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { reviewRun } from "../fixtures/review-run";
import { pendingGate } from "../gates";
import { buildTimeline, type Step } from "../timeline";
import { GateDecision } from "./gate-decision";
import { zoneComments, zoneElement } from "./review-zone";
import { sentBackBy, stepEntries, stepOutline, stepRows } from "./step-entries";
import { StepInput } from "./step-input";

const { spec, events } = reviewRun;

function find(steps: Step[], id: string): Step[] {
  return steps.flatMap((s) => [
    ...(s.id === id ? [s] : []),
    ...find(s.iterations?.flatMap((i) => i.steps) ?? [], id),
    ...find(s.branches?.flatMap((b) => b.steps) ?? [], id),
    ...find(s.orchestrator?.tasks.flatMap((t) => t.steps) ?? [], id),
  ]);
}

describe("the recorded review run", () => {
  const timeline = buildTimeline(events);
  const gates = find(timeline.steps, "approve_pr");

  it("reads a gate the review sent back as Sent back by review", () => {
    const [first] = gates;
    expect(first?.gate?.source).toBe("review");
    expect(first && stepOutline(first)).toBe("Sent back by review (1 comment)");
    expect(first?.gate?.review?.sentBack).toBe(true);
    expect(first?.gate?.review?.counts.high).toBe(1);
  });

  it("names both when the checks sent it back and the review would have too", () => {
    expect(sentBackBy({ source: "checks", alsoReview: true })).toBe(
      "Sent back by checks and review",
    );
    expect(sentBackBy({ source: "checks", alsoReview: false })).toBe("Sent back by checks");
    expect(sentBackBy({ source: "review", alsoReview: false })).toBe("Sent back by review");
  });

  it("keeps the second pass's comments and what the approval dismissed", () => {
    const gate = gates.at(-1)?.gate;
    expect(gate?.decision).toBe("approve");
    expect(gate?.review?.comments.map((c) => [c.path, c.line, c.inDiff])).toEqual([
      ["form.py", 3, true],
      ["README.md", 1, false],
    ]);
    expect(gate?.dismissed).toHaveLength(1);
  });

  it("shows the review on the gate's step, with the dismissed comment marked", () => {
    const gate = gates.at(-1)?.gate;
    if (!gate) throw new Error("no gate");
    render(<GateDecision gate={gate} />);

    expect(screen.getByText("Name this.")).toBeTruthy();
    expect(screen.getByText("Dismissed")).toBeTruthy();
    expect(screen.getByTestId("review-tile")).toBeTruthy();
  });

  it("gives the waiting gate its review", () => {
    const waitingAt = events.findIndex((e) => e.type === "gate_waiting");
    const waiting = pendingGate(events.slice(0, waitingAt + 1));
    expect(waiting?.review?.comments).toHaveLength(2);
    expect(waiting?.review?.blockAt).toBe("high");
  });

  it("shows Reviewing <writer> and what the review agent was given on its Input tab", () => {
    const [lens] = find(timeline.steps, "review_security");
    expect(lens?.reviewInput).toEqual({
      of: "implement",
      spec: null,
      specVersion: null,
      files: 1,
      added: 3,
      removed: 0,
      evidence: false,
    });
    const [row] = stepRows(stepEntries(lens ? [lens] : []));
    if (!row) throw new Error("no row");
    render(<StepInput runId="run-1" row={row} spec={spec} runInput={null} first={false} />);

    const given = screen.getByTestId("review-input");
    expect(given.textContent).toContain("Reviewing");
    expect(given.textContent).toContain("implement");
    expect(given.textContent).toContain("Spec: none");
    expect(given.textContent).toContain("Diff: 1 file +3 -0");
    expect(given.textContent).toContain("Evidence from the checks: no");
  });
});

describe("a comment in the diff (view zone)", () => {
  const message = "<img src=x onerror=alert(1)>";
  const comment = {
    fingerprint: "fp",
    severity: "high" as const,
    lenses: ["security", "performance"],
    message,
    blocking: true,
    line: 3,
  };

  it("holds the severity, the lenses and the message as text nodes only", () => {
    const zone = zoneElement(comment);

    expect(zone.querySelector("img")).toBeNull();
    expect(zone.textContent).toContain(message);
    expect(zone.textContent).toContain("High");
    expect(zone.textContent).toContain("Blocking");
    expect(zone.textContent).toContain("security and performance");
  });

  it("takes only the comments on a line of the file's own diff", () => {
    const base = {
      ...comment,
      category: "x",
      path: "form.py",
      endLine: null,
      inDiff: true,
      nodeId: "w",
    };
    const picked = zoneComments(
      [
        base,
        { ...base, fingerprint: "other-file", path: "api.py" },
        { ...base, fingerprint: "other-writer", nodeId: "v" },
        { ...base, fingerprint: "outside", inDiff: false },
        { ...base, fingerprint: "no-line", line: null as unknown as number },
      ],
      { nodeId: "w", path: "form.py" },
    );

    expect(picked.map((c) => c.fingerprint)).toEqual(["fp"]);
  });
});
