import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { orchestratorRun, orchestratorRunUntil } from "../fixtures/orchestrator-run";
import { specParents } from "../spec-parents";
import { buildTimeline } from "../timeline";
import type { RunEvent } from "../types";
import { StepList } from "./step-list";
import {
  defaultEntry,
  findEntry,
  stepEntries,
  stepOutline,
  stepRows,
  type StepEntry,
} from "./step-entries";
import { StepInput } from "./step-input";
import { StepOutput } from "./step-output";
import { StepUsage } from "./step-usage";

const parents = specParents(orchestratorRun.spec.root);

function entriesOf(events: RunEvent[]): StepEntry[] {
  return stepEntries(buildTimeline(events, parents).steps);
}

const all = entriesOf(orchestratorRun.events);
const seqOf = (type: string, nth = 0) =>
  orchestratorRun.events.filter((e) => e.type === type && e.node_id === "fix")[nth]!.seq;

describe("the step list of an orchestrator run (6.4)", () => {
  it("nests each task under its round, keyed by the task id", () => {
    expect(all.map((e) => [e.kind, e.key, e.depth])).toEqual([
      ["step", "scan", 0],
      ["step", "fix", 0],
      ["scope", "fix~round-1", 1],
      ["scope", "fix.a", 2],
      ["step", "fix.a/fixer", 3],
      ["scope", "fix.b", 2],
      ["step", "fix.b/fixer", 3],
      ["scope", "fix.c", 2],
      ["step", "fix.c/fixer", 3],
      ["scope", "fix.d", 2],
      ["scope", "fix~round-2", 1],
      ["scope", "fix.b2", 2],
      ["step", "fix.b2/fixer", 3],
      ["scope", "fix.c2", 2],
      ["step", "fix.c2/fixer", 3],
    ]);
  });

  it("has no round headings while there is one round", () => {
    const live = entriesOf(orchestratorRunUntil(seqOf("plan_made")));
    expect(live.filter((e) => e.kind === "scope").map((e) => [e.key, e.depth])).toEqual([
      ["fix.a", 1],
      ["fix.b", 1],
      ["fix.c", 1],
      ["fix.d", 1],
    ]);
  });

  it("names a task by its id and title, and says why it failed or was dropped", () => {
    const scope = (key: string) => all.find((e) => e.kind === "scope" && e.key === key)!;
    expect(scope("fix.a")).toMatchObject({ name: "a", itemKind: "Fix a", status: "completed" });
    expect(scope("fix.c")).toMatchObject({
      status: "failed",
      note: "conflicts with earlier tasks on src/app.py",
    });
    expect(scope("fix.d")).toMatchObject({ status: "dropped" });
    expect(scope("fix~round-2")).toMatchObject({ itemKind: "replanned after 2 failures" });
  });

  it("gives each worker's step its task", () => {
    expect(findEntry(all, "fix.b2/fixer")?.task?.id).toBe("b2");
    expect(findEntry(all, "scan")?.task).toBeNull();
  });

  it("says how far the orchestrator got", () => {
    const fix = (events: RunEvent[]) =>
      stepOutline(buildTimeline(events, parents).steps.find((s) => s.id === "fix")!);
    expect(fix(orchestratorRunUntil(seqOf("plan_made") - 1))).toBe("Planning");
    expect(fix(orchestratorRunUntil(seqOf("task_completed")))).toBe("0 of 4 tasks · 1 failed");
    expect(fix(orchestratorRunUntil(seqOf("plan_made", 1)))).toBe(
      "1 of 6 tasks · 2 failed · round 2",
    );
    expect(fix(orchestratorRun.events)).toBe(
      "3 of 6 tasks · 2 failed · 2 rounds · merged 3 into agent/run/fix",
    );
  });

  it("follows the latest running task while live", () => {
    // b2 and c2 both started; c2 is the latest.
    const live = entriesOf(orchestratorRunUntil(seqOf("task_started", 4) + 2));
    expect(defaultEntry(live, true)?.key).toBe("fix.c2/fixer");
  });

  it("shows tasks with their status words, a dropped one without a status colour", () => {
    render(
      <StepList entries={all} selected={null} now={0} kindOf={() => null} onSelect={() => {}} />,
    );
    const dropped = screen
      .getAllByTestId("step-scope")
      .find((e) => e.getAttribute("data-key") === "fix.d")!;
    expect(within(dropped).getByText("Dropped").className).toContain("sr-only");
    expect(dropped.innerHTML).not.toMatch(/status-(failed|succeeded|running)/);
    expect(within(dropped).getByTestId("step-scope-note").textContent).toContain(
      "Dropped: the round stopped before it started",
    );
  });
});

function fixRow() {
  return stepRows(all).find((r) => r.key === "fix")!;
}

describe("an orchestrator's Output", () => {
  it("shows each round's plan, why it was made and how it merged", () => {
    const row = fixRow();
    render(
      <StepOutput
        runId="r1"
        step={row.step}
        row={row}
        kind="orchestrator"
        entries={all}
        onSelect={() => {}}
      />,
    );
    const plan = screen.getByTestId("orchestrator-plan");
    expect(within(plan).getByTestId("orchestrator-totals").textContent).toContain(
      "6 tasks · 2 rounds · 4 tool calls",
    );
    const [first, second] = within(plan).getAllByTestId("orchestrator-round");
    expect(first.textContent).toContain("Why this plan: One task per module.");
    expect(within(first!).getByTestId("orchestrator-integration").textContent).toContain(
      "Merged a into agent/run/fix",
    );
    expect(within(first!).getByTestId("orchestrator-integration").textContent).toContain(
      "c conflicts with earlier tasks on:",
    );
    expect(second.textContent).toContain("b failed: fixer failed: cannot fix b");
    expect(second.textContent).toContain("d dropped");
    // The hub's JSON answer is the plan above, not shown again.
    expect(plan.parentElement!.textContent).not.toContain('"tasks"');
  });

  it("selects a task's worker step", () => {
    const onSelect = vi.fn();
    const row = fixRow();
    render(
      <StepOutput
        runId="r1"
        step={row.step}
        row={row}
        kind="orchestrator"
        entries={all}
        onSelect={onSelect}
      />,
    );
    const task = screen
      .getAllByTestId("orchestrator-task")
      .find((e) => e.getAttribute("data-task") === "c2")!;
    fireEvent.click(within(task).getByRole("button"));
    expect(onSelect).toHaveBeenCalledWith("fix.c2/fixer");
    // A dropped task ran nothing: nothing to select.
    const dropped = screen
      .getAllByTestId("orchestrator-task")
      .find((e) => e.getAttribute("data-task") === "d")!;
    expect(within(dropped).queryByRole("button")).toBeNull();
  });

  it("renders the hub's words as text, never as HTML", () => {
    const events = orchestratorRun.events.map((e) =>
      e.type === "plan_made" && e.payload?.round === 1
        ? {
            ...e,
            payload: {
              ...e.payload,
              reason: "<b>bold</b>",
              tasks: [{ id: "a", title: "<img src=x onerror=alert(1)>" }],
            },
          }
        : e,
    );
    const entries = entriesOf(events);
    const row = stepRows(entries).find((r) => r.key === "fix")!;
    const { container } = render(
      <StepOutput
        runId="r1"
        step={row.step}
        row={row}
        kind="orchestrator"
        entries={entries}
        onSelect={() => {}}
      />,
    );
    expect(container.querySelector("img, b")).toBeNull();
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeTruthy();
  });
});

describe("an orchestrator's Usage and a task's Input", () => {
  it("lists the hub and each task's cost", () => {
    const row = fixRow();
    render(<StepUsage step={row.step} items={[]} />);
    const list = screen.getByRole("list", { name: "Usage by step" });
    expect(
      within(list)
        .getAllByRole("listitem")
        .map((li) => li.querySelector(".font-mono")?.textContent),
    ).toEqual(["hub", "a", "c", "b2", "c2"]);
  });

  it("names the task a worker ran for", () => {
    const row = findEntry(all, "fix.b2/fixer")!;
    render(
      <StepInput
        runId="r1"
        row={row}
        spec={orchestratorRun.spec}
        runInput="the repo"
        first={false}
      />,
    );
    expect(screen.getByText("Task")).toBeTruthy();
    expect(screen.getByText("Fix b2")).toBeTruthy();
    expect(screen.getByText("round 2")).toBeTruthy();
  });

  it("shows the orchestrator's settings", () => {
    render(
      <StepInput
        runId="r1"
        row={fixRow()}
        spec={orchestratorRun.spec}
        runInput="the repo"
        first={false}
      />,
    );
    expect(screen.getByText("6 tasks, 3 at once")).toBeTruthy();
    expect(screen.getByText("On failure, up to 1 time")).toBeTruthy();
  });
});
