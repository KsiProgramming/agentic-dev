import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { runEvent } from "../testing";
import { buildTimeline } from "../timeline";
import type { RunEvent } from "../types";
import { stepEntries, stepRows } from "./step-entries";
import { StepOutput } from "./step-output";

function on(node: string, event: RunEvent): RunEvent {
  return { ...event, node_id: node };
}

function routerOutput(events: RunEvent[]) {
  const steps = buildTimeline(events).steps;
  const entries = stepEntries(steps);
  const row = stepRows(entries)[0]!;
  render(
    <StepOutput
      runId="r1"
      step={row.step}
      row={row}
      kind="router"
      entries={entries}
      onSelect={() => {}}
    />,
  );
  return screen.getByTestId("route-choice");
}

const STARTED = { routes: ["clean", "fix_first", "default"], mode: "rule" };

describe("a router's output (4.6)", () => {
  it("says which route it took, by which condition, and marks the others Skipped", () => {
    const when = 'artifacts["findings.json"].findings.exists(f, f.severity in ["high"])';
    const choice = routerOutput([
      on("report_path", runEvent(1, "node_started", STARTED)),
      on("report_path", runEvent(2, "route_chosen", { route: "fix_first", reason: when })),
      on("fix_first_report", runEvent(3, "node_started")),
      on("fix_first_report", runEvent(4, "node_completed")),
      on("report_path", runEvent(5, "node_completed", { route: "fix_first" })),
    ]);

    expect(choice.textContent).toContain("Took route fix_first");
    expect(within(choice).getByText(when).className).toContain("font-mono");
    const routes = within(choice).getAllByRole("listitem");
    expect(routes.map((r) => r.textContent)).toEqual([
      "cleanSkipped",
      "Donefix_first", // The status marker's label, for screen readers.
      "defaultSkipped",
    ]);
  });

  it("gives a classifier's reason as text, and the step list its route under it", () => {
    const choice = routerOutput([
      on("kind", runEvent(1, "node_started", { routes: ["bug", "feature"], mode: "classifier" })),
      on("kind", runEvent(2, "message", { text: '{"route": "bug", "reason": "It crashes."}' })),
      on("kind", runEvent(3, "route_chosen", { route: "bug", reason: "It crashes." })),
      on("fix", runEvent(4, "node_started")),
    ]);

    expect(within(choice).getByText("Why: It crashes.")).toBeTruthy();
    // The classifier's JSON answer is the choice, not shown again as the router's answer.
    expect(screen.queryByTestId("step-answer")).toBeNull();
    expect(screen.getByRole("list", { name: "Steps inside" }).textContent).toContain("fix");
  });

  it("explains the default and says so while it is still choosing", () => {
    const defaulted = routerOutput([
      on("report_path", runEvent(1, "node_started", STARTED)),
      on(
        "report_path",
        runEvent(2, "route_chosen", { route: "default", reason: "no route matched" }),
      ),
    ]);
    expect(defaulted.textContent).toContain("No route's condition held, so it took the default.");
  });

  it("says it is choosing before it chose", () => {
    const choosing = routerOutput([on("report_path", runEvent(1, "node_started", STARTED))]);

    expect(choosing.textContent).toContain("Choosing a route…");
    expect(choosing.textContent).not.toContain("Skipped");
  });
});
