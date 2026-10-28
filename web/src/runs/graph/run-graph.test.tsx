import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { beforeAll, describe, expect, it } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import { mockReactFlow } from "@/testing/react-flow";

import docsRun from "../fixtures/docs-run.json";
import docsSpec from "../fixtures/docs-run-spec.json";
import { buildTimeline, type Step } from "../timeline";
import type { RunEvent } from "../types";
import { RunGraph } from "./run-graph";

/** The first layout loads ELK, which takes a while when the whole suite runs at once. */
const LAYOUT = { timeout: 10_000 };
import type { WorkflowSpec } from "./spec-graph";

const spec = docsSpec as WorkflowSpec;
const events = docsRun as RunEvent[];

beforeAll(mockReactFlow);

function stepsUpTo(seq: number): Step[] {
  return buildTimeline(events.filter((e) => e.seq <= seq)).steps;
}

/** The graph, selecting the node clicked, as the console uses it. */
function Graph({ steps }: { steps: Step[] }) {
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <TooltipProvider>
      <RunGraph spec={spec} steps={steps} selected={selected} onOpen={setSelected} />
    </TooltipProvider>
  );
}

function node(id: string): HTMLElement {
  const found = screen.getAllByTestId("graph-node").find((el) => el.dataset.nodeId === id);
  if (!found) throw new Error(`no graph node ${id}`);
  return found;
}

describe("RunGraph", () => {
  it("draws every node of the spec with its status in words", async () => {
    render(<Graph steps={stepsUpTo(events.find((e) => e.type === "gate_waiting")!.seq)} />);

    await waitFor(() => expect(screen.getAllByTestId("graph-node")).toHaveLength(7), LAYOUT);
    expect(node("list_modules").dataset.status).toBe("completed");
    expect(node("approve").dataset.status).toBe("waiting");
    expect(node("approve").getAttribute("aria-label")).toBe(
      "approve, Needs approval, Open the docs PR?, gate",
    );
    expect(node("document").getAttribute("aria-label")).toBe("document, Done, 3 of 3 items, map");
    // The name holds the visible text word for word (axe reads the text nodes as they come).
    expect(node("approve").textContent).toBe("approve Needs approval Open the docs PR?");
    expect(node("document").textContent).toBe("document Done 3 of 3 items");
    expect(within(node("revise")).getByText("Iteration 2 of 3")).toBeTruthy();
  });

  it("selects the node clicked, and marks it", async () => {
    render(<Graph steps={stepsUpTo(88)} />);

    fireEvent.click(await waitFor(() => node("module-writer"), LAYOUT));

    expect(node("module-writer").getAttribute("aria-pressed")).toBe("true");
    expect(node("approve").getAttribute("aria-pressed")).toBe("false");
  });

  it("lets the pointer reach the nodes, not the pane under them", async () => {
    const { container } = render(<Graph steps={stepsUpTo(88)} />);
    await waitFor(() => node("module-writer"), LAYOUT);

    // jsdom ignores pointer-events on click, so check the style a browser hit-tests with.
    const wrappers = container.querySelectorAll<HTMLElement>(".react-flow__node");
    expect(wrappers).toHaveLength(7);
    for (const wrapper of wrappers) expect(wrapper.style.pointerEvents).toBe("all");
  });

  it("updates a node's status as events arrive, without drawing the graph again", async () => {
    const { rerender } = render(<Graph steps={stepsUpTo(5)} />);
    const before = await waitFor(() => node("document"), LAYOUT);
    expect(before.dataset.status).toBe("not_started");

    rerender(<Graph steps={stepsUpTo(25)} />);

    expect(node("document")).toBe(before);
    expect(node("document").dataset.status).toBe("running");
    expect(within(node("document")).getByText("1 of 3 items")).toBeTruthy();
  });

  it("is reached by keyboard: each node is a button of its own", async () => {
    render(<Graph steps={stepsUpTo(88)} />);
    const writer = await waitFor(() => node("module-writer"), LAYOUT);

    expect(writer.tagName).toBe("BUTTON");
    expect(writer.tabIndex).toBe(0);
    act(() => writer.focus());
    expect(document.activeElement).toBe(writer);
  });

  it("shows a skeleton while the graph is laid out", () => {
    render(<Graph steps={stepsUpTo(5)} />);

    expect(screen.getByText("Drawing the workflow graph…")).toBeTruthy();
  });
});

describe("RunGraph on a router", () => {
  const agent = (id: string): WorkflowSpec["root"] => ({
    type: "agent",
    id,
    role: "R",
    instructions: "go",
    tools: [],
  });
  const routed: WorkflowSpec = {
    spec_version: "0",
    id: "w",
    name: "W",
    root: {
      type: "router",
      id: "report_path",
      routes: [{ id: "clean", when: "true", then: agent("clean_report") }],
      default: agent("standard_report"),
    },
  };

  it("draws each route as a labelled group, the one not taken skipped", async () => {
    const [started] = buildTimeline([
      { ...events[0]!, seq: 1, type: "node_started", node_id: "report_path", payload: {} },
    ]).steps;
    const router: Step = {
      ...started!,
      router: {
        routes: ["clean", "default"],
        mode: "rule",
        chosen: "default",
        reason: null,
        steps: [],
      },
    };
    render(
      <TooltipProvider>
        <RunGraph spec={routed} steps={[router]} onOpen={() => {}} />
      </TooltipProvider>,
    );

    const routes = await waitFor(() => screen.getAllByTestId("graph-route"), LAYOUT);
    expect(routes.map((r) => [r.dataset.routeId, r.dataset.status])).toEqual([
      ["clean", "skipped"],
      ["default", "not_started"],
    ]);
    expect(routes[0]!.getAttribute("aria-label")).toBe("route clean, Skipped");
    expect(node("clean_report").dataset.status).toBe("skipped");
    expect(node("clean_report").getAttribute("aria-label")).toBe("clean_report, Skipped, R, agent");
    expect(node("report_path").getAttribute("aria-label")).toBe(
      "report_path, Running, Routed to default, router",
    );
  });
});
