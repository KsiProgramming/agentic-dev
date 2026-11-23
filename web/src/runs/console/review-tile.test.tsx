import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { parseEvidence } from "../evidence";
import { parseReview } from "../review";
import { EvidenceStrip } from "./evidence-strip";

const PASSING = parseEvidence({
  version: 1,
  gate: "check",
  node: "writer",
  path: ".",
  checks: [{ kind: "build", status: "passed", required: true, summary: "1 module built" }],
  rounds_left: 2,
});

function found(over: Record<string, unknown> = {}) {
  const comment = (fingerprint: string, severity: string, line: number) => ({
    fingerprint,
    severity,
    category: "security",
    lenses: ["security"],
    path: "a.py",
    line,
    message: "m",
    node_id: "w",
    in_diff: true,
    blocking: false,
  });
  return parseReview({
    from: "review.json",
    version: 1,
    block_at: "high",
    rounds_left: 2,
    comments: [comment("a", "high", 1), comment("b", "high", 2), comment("c", "low", 3)],
    failed_lenses: [],
    counts: { high: 2, low: 1 },
    truncated: false,
    ...over,
  });
}

describe("the Review tile (13.6)", () => {
  it("shows Passed with the headline when nothing blocks", () => {
    render(<EvidenceStrip evidence={PASSING} review={found()} />);

    const tile = screen.getByTestId("review-tile");
    expect(within(tile).getByText("Review")).toBeTruthy();
    expect(within(tile).getByText("Passed")).toBeTruthy();
    expect(within(tile).getByText("2 high · 3 comments")).toBeTruthy();
  });

  it("shows Sent back, with the writer going again", () => {
    render(<EvidenceStrip evidence={null} review={found({ sent_back: true, blocking: 2 })} />);

    expect(within(screen.getByTestId("review-tile")).getByText("Sent back")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("The writer goes again");
  });

  it("shows Could not run when a lens failed", () => {
    render(<EvidenceStrip evidence={null} review={found({ failed_lenses: ["performance"] })} />);

    const tile = screen.getByTestId("review-tile");
    expect(within(tile).getByText("Could not run")).toBeTruthy();
    expect(within(tile).getByText(/1 lens could not run/)).toBeTruthy();
  });

  it("is one full-width cell, so it never leaves an empty cell", () => {
    render(<EvidenceStrip evidence={PASSING} review={found()} />);

    const strip = screen.getByTestId("review-tile").querySelector("[data-slot='stat-strip']");
    expect(strip?.querySelectorAll("[data-slot='stat-tile']")).toHaveLength(1);
    expect(strip?.className).toContain("md:grid-cols-1");
  });

  it("keeps the checks when there is no review", () => {
    render(<EvidenceStrip evidence={PASSING} />);

    expect(screen.queryByTestId("review-tile")).toBeNull();
    expect(screen.getByTestId("evidence")).toBeTruthy();
  });
});
