import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { orchestratorRun, orchestratorRunUntil } from "../fixtures/orchestrator-run";
import { specParents } from "../spec-parents";
import { buildTimeline } from "../timeline";
import type { RunEvent } from "../types";
import { focusStep, nodeStatuses } from "./node-status";
import { RunMap } from "./run-map";

const { spec } = orchestratorRun;
const parents = specParents(spec.root);
const stepsOf = (events: RunEvent[]) => buildTimeline(events, parents).steps;
const planned = orchestratorRun.events.find((e) => e.type === "plan_made")!.seq;

describe("an orchestrator on the run map (6.4)", () => {
  it("draws its worker hanging off it before the run starts, with no tasks yet", () => {
    render(<RunMap spec={spec} steps={[]} onOpen={() => {}} now={0} />);
    const ids = screen.getAllByTestId("map-node").map((n) => n.getAttribute("data-node"));
    expect(ids).toEqual(["scan", "fix", "fixer"]);
    expect(screen.queryByTestId("map-tasks")).toBeNull();
    expect(screen.getByText("Up to 6 tasks, 3 at a time")).toBeTruthy();
  });

  it("says it is planning, then shows each task as soon as it is planned", () => {
    const { rerender } = render(
      <RunMap
        spec={spec}
        steps={stepsOf(orchestratorRunUntil(planned - 1))}
        onOpen={() => {}}
        now={0}
      />,
    );
    expect(nodeStatuses(spec, stepsOf(orchestratorRunUntil(planned - 1))).get("fix")?.summary).toBe(
      "Planning",
    );
    expect(screen.queryByTestId("map-task")).toBeNull();
    rerender(
      <RunMap
        spec={spec}
        steps={stepsOf(orchestratorRunUntil(planned))}
        onOpen={() => {}}
        now={0}
      />,
    );
    const tasks = screen.getAllByTestId("map-task");
    expect(tasks.map((t) => [t.getAttribute("data-task"), t.getAttribute("data-status")])).toEqual([
      ["a", "pending"],
      ["b", "pending"],
      ["c", "pending"],
      ["d", "pending"],
    ]);
    expect(tasks[0]!.textContent).toContain("Not started");
  });

  it("shows how each task ended and what it cost, a dropped one dashed", () => {
    render(
      <RunMap spec={spec} steps={stepsOf(orchestratorRun.events)} onOpen={() => {}} now={0} />,
    );
    const task = (id: string) =>
      screen.getAllByTestId("map-task").find((t) => t.getAttribute("data-task") === id)!;
    expect(task("a").textContent).toMatch(/Fix a.*\$/);
    expect(task("c").getAttribute("data-status")).toBe("failed");
    expect(task("d").textContent).toContain("Dropped");
    expect(within(task("d")).queryByRole("button")).toBeNull();
    expect(nodeStatuses(spec, stepsOf(orchestratorRun.events)).get("fix")?.summary).toBe(
      "3 of 6 tasks · 2 rounds",
    );
    expect(screen.getByText(/3 of 6 tasks done \(1 dropped\)/)).toBeTruthy();
  });

  it("selects a task's step, its name holding the visible text", () => {
    const onOpenTask = vi.fn();
    const steps = stepsOf(orchestratorRun.events);
    render(<RunMap spec={spec} steps={steps} onOpen={() => {}} onOpenTask={onOpenTask} now={0} />);
    const button = screen.getByRole("button", { name: /^b2, Done, ?Fix b2/ });
    fireEvent.click(button);
    expect(onOpenTask).toHaveBeenCalledWith(
      steps[1]!.orchestrator!.tasks.find((t) => t.id === "b2"),
    );
  });

  it("focuses a worker node inside the tasks that ran it", () => {
    const focused = focusStep(stepsOf(orchestratorRun.events), "fixer");
    expect(focused?.id).toBe("fix");
    expect(focused?.orchestrator?.tasks.map((t) => t.id)).toEqual(["a", "b", "c", "b2", "c2"]);
  });
});
