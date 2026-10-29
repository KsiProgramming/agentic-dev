import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import docsSpec from "../fixtures/docs-run-spec.json";
import { RunMap } from "./run-map";
import type { WorkflowSpec } from "./spec-graph";

const spec = docsSpec as WorkflowSpec;

const agent = (id: string): WorkflowSpec["root"] => ({
  type: "agent",
  id,
  role: `role of ${id}`,
  instructions: "go",
  tools: [],
});

const withRouter: WorkflowSpec = {
  spec_version: "0",
  id: "w",
  name: "W",
  root: {
    type: "sequence",
    id: "main",
    steps: [
      agent("triage"),
      {
        type: "router",
        id: "report_path",
        routes: [{ id: "clean", when: "true", then: agent("clean_report") }],
        default: agent("standard_report"),
      },
    ],
  },
};

describe("RunMap", () => {
  it("draws one card per node, sequences left out, before the run reaches them", () => {
    render(<RunMap spec={spec} steps={[]} onOpen={() => {}} now={0} />);
    const cards = screen.getAllByTestId("map-node");
    expect(cards.map((c) => c.dataset.node)).toContain("list_modules");
    expect(cards.every((c) => c.dataset.status === "not_started")).toBe(true);
    // A card names itself with its status and kind (WCAG 2.5.3: visible text first).
    expect(cards[0]!.getAttribute("aria-label")).toMatch(/^list_modules, Not started, tool$/);
    expect(screen.getByTestId("run-map").textContent).toContain("0 of");
  });

  it("hangs a router's routes off it, the default last", () => {
    render(<RunMap spec={withRouter} steps={[]} onOpen={() => {}} now={0} />);
    const routes = screen.getAllByTestId("map-route").map((r) => r.textContent);
    expect(routes).toEqual([expect.stringContaining("clean"), expect.stringContaining("default")]);
  });

  it("selects a node's step on click and marks the selected one", () => {
    const onOpen = vi.fn();
    render(<RunMap spec={spec} steps={[]} selected="combine" onOpen={onOpen} now={0} />);
    const map = screen.getByRole("region", { name: "Workflow map" });
    const combine = within(map)
      .getAllByTestId("map-node")
      .find((c) => c.dataset.node === "combine")!;
    expect(combine.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(combine);
    expect(onOpen).toHaveBeenCalledWith("combine");
  });
});
