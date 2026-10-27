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
    render(<Graph steps={stepsUpTo(84)} />);

    await waitFor(() => expect(screen.getAllByTestId("graph-node")).toHaveLength(7));
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

    fireEvent.click(await waitFor(() => node("module-writer")));

    expect(node("module-writer").getAttribute("aria-pressed")).toBe("true");
    expect(node("approve").getAttribute("aria-pressed")).toBe("false");
  });

  it("lets the pointer reach the nodes, not the pane under them", async () => {
    const { container } = render(<Graph steps={stepsUpTo(88)} />);
    await waitFor(() => node("module-writer"));

    // jsdom ignores pointer-events on click, so check the style a browser hit-tests with.
    const wrappers = container.querySelectorAll<HTMLElement>(".react-flow__node");
    expect(wrappers).toHaveLength(7);
    for (const wrapper of wrappers) expect(wrapper.style.pointerEvents).toBe("all");
  });

  it("updates a node's status as events arrive, without drawing the graph again", async () => {
    const { rerender } = render(<Graph steps={stepsUpTo(5)} />);
    const before = await waitFor(() => node("document"));
    expect(before.dataset.status).toBe("not_started");

    rerender(<Graph steps={stepsUpTo(25)} />);

    expect(node("document")).toBe(before);
    expect(node("document").dataset.status).toBe("running");
    expect(within(node("document")).getByText("1 of 3 items")).toBeTruthy();
  });

  it("is reached by keyboard: each node is a button of its own", async () => {
    render(<Graph steps={stepsUpTo(88)} />);
    const writer = await waitFor(() => node("module-writer"));

    expect(writer.tagName).toBe("BUTTON");
    expect(writer.tabIndex).toBe(0);
    act(() => writer.focus());
    expect(document.activeElement).toBe(writer);
  });
});
