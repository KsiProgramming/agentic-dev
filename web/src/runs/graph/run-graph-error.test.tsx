import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import { mockReactFlow } from "@/testing/react-flow";

import { RunGraph } from "./run-graph";
import type { WorkflowSpec } from "./spec-graph";

const layoutSpec = vi.hoisted(() => vi.fn());

vi.mock("./spec-graph", async (original) => ({
  ...(await original<typeof import("./spec-graph")>()),
  layoutSpec,
}));

beforeAll(mockReactFlow);

const spec: WorkflowSpec = {
  spec_version: "0",
  id: "w",
  name: "W",
  root: { type: "agent", id: "solo", role: "R", instructions: "go", tools: [] },
};

describe("RunGraph when the layout fails", () => {
  it("says so, and Retry lays it out again", async () => {
    const { layoutSpec: real } =
      await vi.importActual<typeof import("./spec-graph")>("./spec-graph");
    layoutSpec.mockRejectedValueOnce(new Error("ELK failed")).mockImplementation(real);
    render(
      <TooltipProvider>
        <RunGraph spec={spec} steps={[]} onOpen={() => {}} />
      </TooltipProvider>,
    );

    expect(
      await screen.findByText("Could not draw the workflow graph.", {}, { timeout: 10_000 }),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(screen.getAllByTestId("graph-node")).toHaveLength(1), {
      timeout: 10_000,
    });
    expect(layoutSpec).toHaveBeenCalledTimes(2);
  });
});
