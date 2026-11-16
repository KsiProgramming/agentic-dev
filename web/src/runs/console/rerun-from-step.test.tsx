import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json, renderWithQueries, stubApi } from "@/testing/api";
import { DEFAULT_WORKSPACE_ID } from "@/workspace";
import type { NodeManifest } from "@/workflows/node-types";

import docsSpec from "../fixtures/docs-run-spec.json";
import type { SpecNode, WorkflowSpec } from "../graph/spec-graph";
import { runEvent } from "../testing";
import {
  carriedSteps,
  isTopLevelStep,
  lastTopLevelStep,
  RerunFromStepButton,
  rerunFrom,
} from "./rerun-from-step";

const nav = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: nav.push }) }));

const NODE_TYPES = JSON.parse(
  readFileSync(resolve(__dirname, "../../../../schemas/fixtures/node-types.json"), "utf8"),
) as NodeManifest[];

const RUN_ID = "00000000-0000-0000-0000-000000000001";
const NEW_ID = "00000000-0000-0000-0000-0000000000b2";
const SPEC = docsSpec as unknown as WorkflowSpec;

const REVIEWER = {
  type: "agent",
  id: "reviewer",
  role: "Reviewer",
  instructions: "Fail on purpose.",
} as unknown as SpecNode;

afterEach(() => {
  vi.unstubAllGlobals();
  nav.push.mockReset();
});

describe("rerun from a step (12.4)", () => {
  it("is offered on top-level steps only", () => {
    expect(isTopLevelStep(SPEC, "list_modules")).toBe(true);
    expect(isTopLevelStep(SPEC, "revise")).toBe(true);
    expect(isTopLevelStep(SPEC, "reviewer")).toBe(false); // inside the loop
    expect(isTopLevelStep(null, "list_modules")).toBe(false);
  });

  it("knows the step an ended run ended in: the last top-level step it started", () => {
    expect(
      lastTopLevelStep(SPEC, ["list_modules", "document", "writer", "revise", "reviewer"]),
    ).toBe("revise");
    expect(lastTopLevelStep(SPEC, [])).toBeNull();
  });

  it("sends only the parameters changed, as setParam paths on that step", () => {
    const before = { role: "Reviewer", instructions: "Fail on purpose." };
    const after = { role: "Reviewer", instructions: "Review it kindly." };
    const schema = { type: "object", properties: { role: {}, instructions: {} } };

    expect(rerunFrom(REVIEWER, before, after, schema, true)).toEqual({
      node_id: "reviewer",
      set_params: [{ path: "instructions", value: "Review it kindly." }],
      use_wip: true,
    });
    expect(rerunFrom(REVIEWER, before, before, schema, false).set_params).toEqual([]);
  });

  it("reads the steps a rerun carried over from its run_started", () => {
    expect(carriedSteps([runEvent(1, "run_started", { carried: ["a", "b"] })])).toEqual(["a", "b"]);
    expect(carriedSteps([runEvent(1, "run_started")])).toEqual([]);
  });

  it("starts a new run from the step with its edited instructions", async () => {
    let posted: unknown = null;
    stubApi({
      [`GET /node-types?workspace_id=${DEFAULT_WORKSPACE_ID}`]: () => json(200, NODE_TYPES),
      [`POST /runs/${RUN_ID}/rerun`]: async (request) => {
        posted = await request.json();
        return json(202, { run_id: NEW_ID, status: "queued", events_url: "" });
      },
    });
    renderWithQueries(
      <RerunFromStepButton
        runId={RUN_ID}
        node={REVIEWER}
        wipAvailable={true}
        baseUrl="http://api.test"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Rerun from here" }));
    const instructions = await screen.findByLabelText(/Instructions/);
    fireEvent.change(instructions, { target: { value: "Review it kindly." } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Start from its uncommitted work" }));
    fireEvent.click(screen.getByRole("button", { name: "Start rerun" }));

    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(`/runs/${NEW_ID}`));
    expect(posted).toEqual({
      from: {
        node_id: "reviewer",
        set_params: [{ path: "instructions", value: "Review it kindly." }],
        use_wip: true,
      },
    });
  });

  it("offers the uncommitted work only when there is some", async () => {
    stubApi({
      [`GET /node-types?workspace_id=${DEFAULT_WORKSPACE_ID}`]: () => json(200, NODE_TYPES),
    });
    renderWithQueries(
      <RerunFromStepButton
        runId={RUN_ID}
        node={REVIEWER}
        wipAvailable={false}
        baseUrl="http://api.test"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Rerun from here" }));
    await screen.findByLabelText(/Instructions/);
    expect(screen.queryByRole("checkbox", { name: "Start from its uncommitted work" })).toBeNull();
  });

  it("says why the node types could not load, with a retry", async () => {
    stubApi({
      [`GET /node-types?workspace_id=${DEFAULT_WORKSPACE_ID}`]: () => json(500, { detail: "no" }),
    });
    renderWithQueries(
      <RerunFromStepButton
        runId={RUN_ID}
        node={REVIEWER}
        wipAvailable={false}
        baseUrl="http://api.test"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Rerun from here" }));
    expect(await screen.findByRole("button", { name: /Retry/ })).toBeTruthy();
  });
});
