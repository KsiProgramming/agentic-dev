import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ac2Run } from "../fixtures/ac2-run";
import { specParents } from "../spec-parents";
import { buildTimeline } from "../timeline";
import { flowLayout } from "./flow-layout";
import { nodeStatuses } from "./node-status";
import { RunMap } from "./run-map";
import { allSpecNodes } from "./spec-graph";

/** AC-2 (6.8): the run of a flow with a parallel, an orchestrator in a loop, a gate and a pull
 * request is drawn where its spec draws each node, each with the status its events give. */

const { spec, events } = ac2Run;
const steps = buildTimeline(events, specParents(spec.root)).steps;

/** The graph a view draws: its cards and the edges between them, wraps aside (a sequence wraps
 * to its pane's width, which differs between the canvas and the run map). */
function drawnGraph(container: HTMLElement) {
  const cards = [...container.querySelectorAll("[data-flow-card]")].map((c) =>
    c.getAttribute("data-flow-card"),
  );
  const edges = [...container.querySelectorAll("g[data-edge]")]
    .filter((g) => g.getAttribute("data-edge") !== "wrap")
    .map((g) => `${g.getAttribute("data-from")}→${g.getAttribute("data-to")}`)
    .sort();
  return { cards, edges };
}

describe("the AC-2 run on the run map (6.8)", () => {
  it("draws every node of the spec, and only those, in the spec's flow", () => {
    const { container } = render(
      <RunMap spec={spec} steps={steps} onOpen={() => {}} now={0} layout="flow" />,
    );

    const layout = flowLayout(spec);
    const drawn = drawnGraph(container);
    expect(drawn.cards).toEqual(layout.cards.map((c) => c.node.id));
    expect(drawn.cards).toEqual([
      "explore",
      "code_analyst",
      "test_analyst",
      "review_loop",
      "implement",
      "engineer",
      "synthesizer",
      "reviewer",
      "approve_pr",
      "publish",
    ]);
    expect(drawn.edges).toEqual(
      layout.edges
        .filter((e) => e.kind !== "wrap")
        .map((e) => `${e.from}→${e.to}`)
        .sort(),
    );
    // The loop goes back from its last step to itself.
    expect(container.querySelector('g[data-edge="back"]')?.getAttribute("data-from")).toBe(
      "reviewer",
    );
  });

  it("gives every drawn node the status its events give: all of them completed", () => {
    const states = nodeStatuses(spec, steps);
    const drawn = allSpecNodes(spec)
      .filter((n) => n.type !== "sequence")
      .map((n) => n.id);

    expect(drawn.map((id) => [id, states.get(id)?.status])).toEqual(
      drawn.map((id) => [id, "completed"]),
    );
    render(<RunMap spec={spec} steps={steps} onOpen={() => {}} now={0} layout="flow" />);
    for (const node of screen.getAllByTestId("map-node")) {
      expect(node.getAttribute("data-status"), node.getAttribute("data-node") ?? "").toBe(
        "completed",
      );
    }
  });

  it("shows both passes of the loop and each pass's tasks on the orchestrator", () => {
    const states = nodeStatuses(spec, steps);
    expect(states.get("review_loop")?.summary).toMatch(/2/);

    render(<RunMap spec={spec} steps={steps} onOpen={() => {}} now={0} layout="flow" />);
    const tasks = screen.getAllByTestId("map-task");
    expect(tasks.map((t) => [t.getAttribute("data-task"), t.getAttribute("data-status")])).toEqual(
      [["tests", "completed"]],
    );
  });
});
