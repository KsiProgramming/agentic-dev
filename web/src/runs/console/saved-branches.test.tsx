import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { API, json, renderWithQueries, stubApi } from "@/testing/api";

import { summarizePayload } from "../summarize";
import { runEvent } from "../testing";
import { buildTimeline } from "../timeline";
import type { RunEvent } from "../types";
import { EVENT_TYPES } from "../types";
import { stepEntries, stepRows } from "./step-entries";
import { StepOutput } from "./step-output";

const BRANCH = "agent/00000000-0000-0000-0000-000000000001/writer";
const HEAD = "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b";
const NEWER = "2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c";

function on(nodeId: string, event: RunEvent): RunEvent {
  return { ...event, node_id: nodeId };
}

function saved(seq: number, head: string, version: number, commits: number): RunEvent {
  return on(
    "writer",
    runEvent(seq, "branch_saved", {
      key: "writer",
      branch: BRANCH,
      kind: "writer",
      version,
      head,
      commits,
      size: 512,
    }),
  );
}

function writerRun(...more: RunEvent[]) {
  return buildTimeline([
    runEvent(1, "run_started"),
    on("writer", runEvent(2, "node_started")),
    on("writer", runEvent(3, "message", { text: "committed" })),
    on("writer", runEvent(4, "node_completed")),
    ...more,
  ]);
}

describe("saved branches (12.2)", () => {
  it("are streamed live", () => {
    for (const type of ["branch_saved", "branch_save_failed", "branches_restored"]) {
      expect(EVENT_TYPES).toContain(type);
    }
    // The orchestrator's and router's own events, which its live view is built from (6.x).
    for (const type of ["plan_made", "task_started", "task_completed", "branch_integrated"]) {
      expect(EVENT_TYPES).toContain(type);
    }
  });

  it("keep the latest save of each branch on the step that committed", () => {
    const timeline = writerRun(saved(5, HEAD, 1, 1), saved(6, NEWER, 2, 3));

    const [writer] = timeline.steps;
    expect(timeline.steps).toHaveLength(1);
    expect(writer?.savedBranches).toEqual([
      {
        branch: BRANCH,
        key: "writer",
        kind: "writer",
        version: 2,
        head: NEWER,
        commits: 3,
        at: runEvent(6, "x").created_at,
        error: null,
      },
    ]);
  });

  it("keep what was saved before a save that failed, with its reason", () => {
    const failed = on(
      "writer",
      runEvent(6, "branch_save_failed", { key: "writer", branch: BRANCH, error: "too large" }),
    );

    const [writer] = writerRun(saved(5, HEAD, 1, 1), failed).steps;

    expect(writer?.savedBranches[0]).toMatchObject({ head: HEAD, commits: 1, error: "too large" });
  });

  it("add no step for a writer the events do not reach", () => {
    const stray = on("elsewhere", runEvent(5, "branch_saved", { branch: BRANCH, head: HEAD }));

    expect(writerRun(stray).steps.map((s) => s.id)).toEqual(["writer"]);
  });

  it("read as one line in the raw events", () => {
    expect(summarizePayload(saved(5, HEAD, 1, 3))).toBe(`${BRANCH}: 3 commits saved`);
    expect(
      summarizePayload(runEvent(7, "branches_restored", { branches: [{ branch: BRANCH }] })),
    ).toBe("1 saved branch restored into a fresh sandbox");
    expect(
      summarizePayload(runEvent(8, "branch_save_failed", { branch: BRANCH, error: "too large" })),
    ).toBe(`${BRANCH} not saved: too large`);
  });

  it("show in the step's output, a failed save as an error", () => {
    const failed = on(
      "writer",
      runEvent(6, "branch_save_failed", { key: "writer", branch: BRANCH, error: "too large" }),
    );
    const timeline = writerRun(saved(5, HEAD, 1, 1), failed);
    const entries = stepEntries(timeline.steps);
    const [row] = stepRows(entries);
    if (!row) throw new Error("no row");

    renderWithQueries(
      <StepOutput
        runId="run-1"
        step={row.step}
        row={row}
        kind="agent"
        entries={entries}
        onSelect={() => undefined}
      />,
    );

    const section = screen.getByRole("region", { name: "Commits saved" });
    expect(within(section).getByText(BRANCH)).toBeTruthy();
    expect(within(section).getByText("1 commit")).toBeTruthy();
    expect(within(section).getByRole("button", { name: "Copy commit 1a2b3c4d" })).toBeTruthy();
    expect(
      within(section).getByText("Not saved: too large. Its newer commits are only in the sandbox."),
    ).toBeTruthy();
  });
});

describe("a saved branch's changes (12.3)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("open read-only from what was saved", async () => {
    const fetch = stubApi({
      "GET /runs/run-1/changes": () =>
        json(200, [
          {
            node_id: "writer",
            key: "writer",
            branch: BRANCH,
            kind: "writer",
            version: 1,
            head: HEAD,
            commits: 1,
            saved_at: "2026-11-15T10:00:00Z",
            changes: [
              {
                node_id: "writer",
                path: "NOTES.md",
                old_path: null,
                status: "added",
                editable: true,
                reason: null,
                before: null,
                after: "notes\n",
              },
            ],
            changes_error: null,
            bundle_removed_at: null,
          },
        ]),
    });
    const timeline = writerRun(saved(5, HEAD, 1, 1));
    const entries = stepEntries(timeline.steps);
    const [row] = stepRows(entries);
    if (!row) throw new Error("no row");
    renderWithQueries(
      <StepOutput
        runId="run-1"
        step={row.step}
        row={row}
        kind="agent"
        entries={entries}
        onSelect={() => undefined}
        baseUrl={API}
      />,
    );
    // Nothing is fetched until it is asked for.
    expect(fetch).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: `View changes on ${BRANCH}` }));

    const sheet = await screen.findByTestId("gate-review");
    expect(within(sheet).getByRole("heading", { name: "What writer changed" })).toBeTruthy();
    expect(await within(sheet).findAllByText("NOTES.md")).not.toHaveLength(0);
    expect(within(sheet).getByText("1 commit")).toBeTruthy();
    expect(within(sheet).queryByRole("button", { name: /Approve/ })).toBeNull();
  });
});
