import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { flowLayout } from "./flow-layout";
import { SpecFlow, SpecView } from "./spec-flow";
import type { WorkflowSpec } from "./spec-graph";

const TEAM = JSON.parse(
  readFileSync(
    resolve(
      __dirname,
      "../../../../packages/engine/tests/fixtures/specs/valid/team-review-pr.json",
    ),
    "utf8",
  ),
) as WorkflowSpec;

const card = (node: { id: string }) => <button type="button">{node.id}</button>;

describe("a workflow drawn as a flow (5.9)", () => {
  it("draws the cards in run order, so the tab order follows the flow", () => {
    render(<SpecFlow spec={TEAM} renderCard={card} />);
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual([
      "implement",
      "engineer",
      "task_review",
      "synthesizer",
      "reviewer",
      "decision",
      "approve_pr",
      "open_pr",
      "report_changes",
    ]);
  });

  it("puts each card in its cell, frames the worker and draws every edge", () => {
    const { container } = render(<SpecFlow spec={TEAM} renderCard={card} />);
    const synthesizer = container.querySelector('[data-flow-card="synthesizer"]') as HTMLElement;
    expect(synthesizer.style.gridColumn).toBe("4");
    expect(screen.getByTestId("flow-lane").textContent).toBe("Each task");
    expect(container.querySelectorAll("[data-edge]")).toHaveLength(flowLayout(TEAM).edges.length);
    // A route's name is on its edge, not a card of its own.
    expect(container.querySelector("svg")!.textContent).toContain("ok");
    expect(container.querySelector("svg")!.textContent).toContain("default");
  });

  it("dashes the route a router did not take", () => {
    const { container } = render(
      <SpecFlow spec={TEAM} renderCard={card} isSkipped={(r) => r === "decision:route:default"} />,
    );
    const dashed = [...container.querySelectorAll('[data-edge="fork"] path')].filter(
      (p) => p.getAttribute("stroke-dasharray") !== null,
    );
    expect(dashed).toHaveLength(1);
  });

  it("draws the vertical tree where the flow does not fit", () => {
    render(<SpecView spec={TEAM} renderCard={card} />);
    expect(screen.queryByTestId("spec-flow")).toBeNull();
    render(<SpecView spec={TEAM} renderCard={card} layout="flow" />);
    expect(screen.getByTestId("spec-flow")).toBeTruthy();
  });
});
