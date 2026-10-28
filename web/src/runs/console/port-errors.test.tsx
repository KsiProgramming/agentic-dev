import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { WorkflowSpec } from "../graph/spec-graph";
import { runEvent } from "../testing";
import { buildTimeline, type PortFailure } from "../timeline";
import { PortErrors } from "./port-errors";
import { stepEntries, stepRows } from "./step-entries";
import { StepInput } from "./step-input";
import { StepOutput } from "./step-output";

const ERROR =
  "output of 'summarizer' does not match its output_schema at /findings/0/severity: " +
  "'urgent' is not one of ['low', 'high']";

function portFailure(errors: number): PortFailure {
  return {
    side: "output",
    fromNodeId: null,
    errors: Array.from({ length: errors }, (_, i) => ({
      pointer: `/findings/${i}/severity`,
      message: `'urgent${i}' is not one of ['low', 'high']`,
    })),
  };
}

function failedRun() {
  return buildTimeline([
    runEvent(1, "run_started"),
    runEvent(2, "node_started"),
    runEvent(3, "message", { text: '{"findings": [{"severity": "urgent"}]}' }),
    runEvent(4, "node_failed", {
      error: ERROR,
      port: {
        side: "output",
        node_id: "summarizer",
        from_node_id: null,
        errors: [
          { pointer: "/findings/0/severity", message: "'urgent' is not one of ['low', 'high']" },
        ],
      },
    }),
    runEvent(5, "run_failed", { stopped_at: "summarizer" }),
  ]);
}

describe("typed ports in the timeline", () => {
  it("keeps the port that failed a step", () => {
    const [step] = failedRun().steps;
    expect(step?.status).toBe("failed");
    expect(step?.error).toBe(ERROR);
    expect(step?.port).toEqual({
      side: "output",
      fromNodeId: null,
      errors: [
        { pointer: "/findings/0/severity", message: "'urgent' is not one of ['low', 'high']" },
      ],
    });
  });

  it("has no port for a step that failed for another reason", () => {
    const timeline = buildTimeline([
      runEvent(1, "node_started"),
      runEvent(2, "node_failed", { error: "model refused" }),
    ]);
    expect(timeline.steps[0]?.port).toBeNull();
  });
});

describe("PortErrors", () => {
  it("lists each pointer in mono with its message", () => {
    render(<PortErrors stepId="triage" port={portFailure(2)} />);
    const alert = screen.getByTestId("port-errors");
    expect(within(alert).getByText("Wrong shape")).toBeTruthy();
    expect(alert.textContent).toContain("The output of triage does not match its output schema.");
    expect(within(alert).getByText("/findings/1/severity").className).toContain("font-mono");
    expect(within(alert).getByText("'urgent1' is not one of ['low', 'high']")).toBeTruthy();
    // The run's banner announces the failure; this alert does not again.
    expect(alert.getAttribute("role")).toBeNull();
  });

  it("names the step the input came from, and the top level when there is no pointer", () => {
    const port: PortFailure = {
      side: "input",
      fromNodeId: "scan",
      errors: [{ pointer: "", message: "'findings' is a required property" }],
    };
    render(<PortErrors stepId="report" port={port} />);
    const alert = screen.getByTestId("port-errors");
    expect(alert.textContent).toContain(
      "The input from scan does not match the input schema of report.",
    );
    expect(within(alert).getByText("(top level)")).toBeTruthy();
  });

  it("shows five errors, then all of them on request", () => {
    render(<PortErrors stepId="triage" port={portFailure(8)} />);
    const alert = screen.getByTestId("port-errors");
    expect(within(alert).getAllByRole("listitem")).toHaveLength(5);
    const more = within(alert).getByRole("button", { name: "Show all 8" });
    expect(more.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(more);
    expect(within(alert).getAllByRole("listitem")).toHaveLength(8);
    expect(within(alert).getByRole("button", { name: "Show fewer" })).toBeTruthy();
  });

  it("shows agent text as text, never as HTML", () => {
    const port: PortFailure = {
      side: "output",
      fromNodeId: null,
      errors: [{ pointer: "/<b>x</b>", message: "<img src=x onerror=alert(1)> is not valid" }],
    };
    const { container } = render(<PortErrors stepId="triage" port={port} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(container.textContent).toContain("<img src=x onerror=alert(1)> is not valid");
  });
});

describe("StepOutput and StepInput for a typed step", () => {
  it("shows the wrong shape in place of the error line", () => {
    const timeline = failedRun();
    const entries = stepEntries(timeline.steps);
    const [row] = stepRows(entries);
    if (!row) throw new Error("no row");
    render(
      <StepOutput
        runId="run-1"
        step={row.step}
        row={row}
        kind="agent"
        entries={entries}
        onSelect={() => undefined}
      />,
    );
    expect(screen.getByTestId("port-errors").textContent).toContain("/findings/0/severity");
    expect(screen.queryByText(ERROR)).toBeNull();
  });

  it("shows the node's input and output schemas", () => {
    const timeline = failedRun();
    const [row] = stepRows(stepEntries(timeline.steps));
    if (!row) throw new Error("no row");
    const spec: WorkflowSpec = {
      spec_version: "0",
      id: "typed",
      name: "Typed",
      root: {
        type: "agent",
        id: "summarizer",
        role: "Writer",
        instructions: "Summarise.",
        input_schema: { type: "object", required: ["modules"] },
        output_schema: { type: "object", required: ["findings"] },
      },
    };
    render(<StepInput runId="run-1" row={row} spec={spec} runInput={null} first={false} />);
    expect(screen.getByText("Input schema")).toBeTruthy();
    expect(screen.getByText("Output schema")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Copy Output schema of summarizer" })).toBeTruthy();
  });
});
