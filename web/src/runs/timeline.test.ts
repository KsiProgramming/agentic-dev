import { describe, expect, it } from "vitest";

import docsRun from "./fixtures/docs-run.json";
import { runEvent } from "./testing";
import {
  buildTimeline,
  clockAt,
  foldDeltas,
  type MessageTurn,
  type Step,
  type ToolTurn,
} from "./timeline";
import type { RunEvent } from "./types";

const events = docsRun as RunEvent[];

function messages(step: Step): MessageTurn[] {
  return step.turns.filter((t): t is MessageTurn => t.kind === "message");
}

function event(
  seq: number,
  type: string,
  nodeId: string | null,
  payload: RunEvent["payload"] = {},
): RunEvent {
  return { ...runEvent(seq, type, payload), node_id: nodeId };
}

describe("buildTimeline on a recorded docs run", () => {
  const timeline = buildTimeline(events);

  it("lists one step per top-level node, in run order", () => {
    expect(timeline.steps.map((s) => s.id)).toEqual([
      "list_modules",
      "document",
      "combine",
      "revise",
      "approve",
    ]);
    expect(timeline.steps.every((s) => s.status === "completed")).toBe(true);
    expect(timeline.workflowName).toBe("Generate docs");
  });

  it("nests the map's items under the map node, each with its own steps", () => {
    const map = timeline.steps[1]!;
    expect(map.items?.map((i) => [i.index, i.item, i.status])).toEqual([
      [0, "packages/api", "completed"],
      [1, "packages/engine", "completed"],
      [2, "web", "completed"],
    ]);
    expect(map.items?.every((i) => i.steps.map((s) => s.id).join() === "module-writer")).toBe(true);
  });

  it("shows one message block per agent turn, not one per chunk", () => {
    const writer = timeline.steps[1]!.items![0]!.steps[0]!;
    // Reasoning, a note, three tool calls, then the text that the final `message` replaces.
    expect(writer.turns.map((t) => t.kind)).toEqual([
      "reasoning",
      "message",
      "tool",
      "tool",
      "tool",
      "message",
    ]);
    expect(writer.turns[0]).toMatchObject({
      kind: "reasoning",
      text: "The input is a module path.\nI should see what `packages/api` holds before writing.",
    });
    expect(writer.turns.map((t) => (t.kind === "tool" ? t.intent : undefined))).toEqual([
      undefined,
      undefined,
      "See what the module holds",
      null,
      null,
      undefined,
    ]);
    const [plan, page] = messages(writer);
    expect(plan).toMatchObject({
      text: "I will look at the files of `packages/api` first.",
      final: false,
      // Streamed right after the reasoning was written, so its chunks went out as one.
      chunks: 1,
    });
    expect(page).toMatchObject({
      text: "# packages/api\n\nThis module holds the **api** code.\n\n- Entry point\n- Tests\n",
      final: true,
      chunks: 1,
    });
    const deltas = events.filter((e) => e.type === "text_delta").length;
    const blocks = [
      ...timeline.steps.flatMap((s) => [
        ...s.turns,
        ...(s.items ?? []).flatMap((i) => i.steps.flatMap((x) => x.turns)),
        ...(s.iterations ?? []).flatMap((i) => i.steps.flatMap((x) => x.turns)),
      ]),
    ].filter((t) => t.kind === "message").length;
    // 3 writers × (a note and an answer) + 2 reviewer turns, from more chunks.
    expect(blocks).toBe(8);
    expect(deltas).toBeGreaterThan(blocks);
  });

  it("pairs each tool call with its result in one card", () => {
    const listModules = timeline.steps[0]!;
    const card = listModules.turns[0] as ToolTurn;
    expect(card).toMatchObject({ kind: "tool", name: "repo.list_modules", status: "completed" });
    expect(card.output).toContain("packages/engine");
  });

  it("keeps loop iterations apart, with their condition result", () => {
    const loop = timeline.steps[3]!;
    expect(loop.iterations?.map((i) => [i.index, i.conditionMet, i.steps[0]?.id])).toEqual([
      [1, false, "reviewer"],
      [2, true, "reviewer"],
    ]);
    expect(loop.iterations?.[1]?.steps[0]?.usage).toMatchObject({
      costComplete: false,
      inputTokens: 900,
      outputTokens: 40,
    });
  });

  it("records the gate's title and decision", () => {
    expect(timeline.steps[4]!.gate).toEqual({
      title: "Open the docs PR?",
      decision: "approve",
      comment: null,
      changes: [],
      edits: [],
    });
  });

  it("gives the same result for a prefix replayed twice (duplicate seq ignored)", () => {
    const twice = buildTimeline([...events.slice(0, 20), ...events.slice(10)]);
    expect(twice).toEqual(timeline);
  });
});

describe("buildTimeline turn rules", () => {
  it("grows one message while chunks stream, and the message replaces it", () => {
    const streaming = buildTimeline([
      event(1, "node_started", "a"),
      event(2, "text_delta", "a", { text: "Hel" }),
      event(3, "text_delta", "a", { text: "lo wor" }),
      event(4, "text_delta", "a", { text: "ld" }),
    ]);
    expect(streaming.steps[0]!.turns).toEqual([
      { kind: "message", key: 2, text: "Hello world", final: false, chunks: 3 },
    ]);

    const done = buildTimeline([
      event(1, "node_started", "a"),
      event(2, "text_delta", "a", { text: "Hel" }),
      event(3, "message", "a", { text: "Hello." }),
    ]);
    expect(done.steps[0]!.turns).toEqual([
      { kind: "message", key: 2, text: "Hello.", final: true, chunks: 1 },
    ]);
  });

  it("adds a message with no chunks before it as its own turn", () => {
    const timeline = buildTimeline([
      event(1, "node_started", "a"),
      event(2, "tool_call", "a", { call_id: "c1", name: "repo.search", arguments: { q: "x" } }),
      event(3, "tool_result", "a", { call_id: "c1", output: "none" }),
      event(4, "message", "a", { text: "Nothing found." }),
    ]);
    expect(timeline.steps[0]!.turns.map((t) => t.kind)).toEqual(["tool", "message"]);
  });

  it("shows a tool call without a result as running, and an error result as failed", () => {
    const timeline = buildTimeline([
      event(1, "node_started", "a"),
      event(2, "tool_call", "a", { call_id: "c1", name: "repo.read_file" }),
      event(3, "tool_result", "a", { call_id: "c1", output: "no such file", is_error: true }),
      event(4, "tool_call", "a", { call_id: "c2", name: "repo.read_file" }),
    ]);
    const [first, second] = timeline.steps[0]!.turns as ToolTurn[];
    expect(first).toMatchObject({ status: "failed", output: "no such file" });
    expect(second).toMatchObject({ status: "running", output: null });
  });

  it("ignores unknown event types", () => {
    const timeline = buildTimeline([
      event(1, "node_started", "a"),
      event(2, "something_new", "a", { x: 1 }),
    ]);
    expect(timeline.steps[0]!.turns).toEqual([]);
  });

  it("shows a failed node's error, and ends nodes cut off by the run's end", () => {
    const timeline = buildTimeline([
      event(1, "node_started", "a"),
      event(2, "failed", "a", { error: "model refused" }),
      event(3, "node_failed", "a", { error: "model refused" }),
      event(4, "node_started", "b"),
      event(5, "run_cancelled", null, { reason: "cancelled by user" }),
    ]);
    expect(timeline.steps.map((s) => [s.id, s.status, s.error])).toEqual([
      ["a", "failed", "model refused"],
      ["b", "cancelled", null],
    ]);
  });

  it("marks a step waiting at a gate", () => {
    const timeline = buildTimeline([
      event(1, "node_started", "gate"),
      event(2, "gate_waiting", "gate", { title: "Ship it?" }),
    ]);
    expect(timeline.steps[0]).toMatchObject({ status: "waiting", gate: { title: "Ship it?" } });
  });

  it("offers only GitHub pull request URLs as links", () => {
    const ok = buildTimeline([
      event(1, "pr_opened", "publish", { url: "https://github.com/acme/docs/pull/7" }),
    ]);
    const bad = buildTimeline([event(1, "pr_opened", "publish", { url: "javascript:alert(1)" })]);
    expect(ok.steps[0]!.prUrl).toBe("https://github.com/acme/docs/pull/7");
    expect(bad.steps[0]!.prUrl).toBeNull();
  });

  it("names the repo a node created, only if it is the GitHub repo it says", () => {
    const repo = { full_name: "acme/docs-new", url: "https://github.com/acme/docs-new" };
    const ok = buildTimeline([event(1, "repo_created", "create_repo", repo)]);
    const bad = buildTimeline([
      event(1, "repo_created", "create_repo", { ...repo, url: "https://evil.test/acme/docs-new" }),
    ]);
    expect(ok.steps[0]!.createdRepo).toEqual({
      fullName: "acme/docs-new",
      url: "https://github.com/acme/docs-new",
    });
    expect(bad.steps[0]!.createdRepo).toBeNull();
  });
});

describe("foldDeltas", () => {
  it("folds consecutive chunks of one node and item into one row with the full text", () => {
    const rows = foldDeltas(events);
    const textRows = rows.filter((r) => r.kind === "text");
    // Per writer: its reasoning, its note and its page; then the two reviews.
    expect(textRows.map((r) => r.type)).toEqual([
      ...["reasoning_delta", "text_delta", "text_delta"],
      ...["reasoning_delta", "text_delta", "text_delta"],
      ...["reasoning_delta", "text_delta", "text_delta"],
      ...["text_delta", "text_delta"],
    ]);
    expect(textRows[2]).toMatchObject({
      nodeId: "module-writer",
      item: 0,
      text: "# packages/api\n\nThis module holds the **api** code.\n\n- Entry point\n- Tests\n",
    });
    expect(
      rows.some(
        (r) =>
          r.kind === "event" &&
          (r.event.type === "text_delta" || r.event.type === "reasoning_delta"),
      ),
    ).toBe(false);
    // Every event is still there, folded or not.
    const count = rows.reduce((n, r) => n + (r.kind === "text" ? r.events.length : 1), 0);
    expect(count).toBe(events.length);
  });

  it("breaks the fold on another event, node or map item", () => {
    const rows = foldDeltas([
      event(1, "text_delta", "a", { text: "one " }),
      event(2, "text_delta", "a", { text: "two" }),
      event(3, "text_delta", "b", { text: "other node" }),
      event(4, "text_delta", "b", { text: "item 1", item: 1 }),
      event(5, "usage", "b", {}),
      event(6, "text_delta", "b", { text: "after" }),
      event(7, "reasoning_delta", "b", { text: "why" }),
      event(8, "reasoning_delta", "b", { text: " so" }),
      event(9, "text_delta", "b", { text: "then" }),
    ]);
    expect(rows.map((r) => (r.kind === "text" ? `${r.type}: ${r.text}` : r.event.type))).toEqual([
      "text_delta: one two",
      "text_delta: other node",
      "text_delta: item 1",
      "usage",
      "text_delta: after",
      "reasoning_delta: why so",
      "text_delta: then",
    ]);
  });
});

describe("buildTimeline on a parallel", () => {
  const timeline = buildTimeline([
    event(1, "run_started", null),
    event(2, "node_started", "review", { branches: 2, join: "any" }),
    event(3, "parallel_branch_started", "review", { index: 0, branch_id: "fast" }),
    event(4, "parallel_branch_started", "review", { index: 1, branch_id: "slow" }),
    event(5, "node_started", "fast", { branch: 0 }),
    event(6, "node_started", "slow", { branch: 1 }),
    event(7, "message", "fast", { type: "message", text: "first", branch: 0 }),
    event(8, "node_completed", "fast", { branch: 0 }),
    event(9, "node_cancelled", "slow", { branch: 1 }),
    event(10, "parallel_branch_completed", "review", {
      index: 0,
      branch_id: "fast",
      status: "completed",
    }),
    event(11, "parallel_branch_completed", "review", {
      index: 1,
      branch_id: "slow",
      status: "cancelled",
      error: "cancelled: the join was decided without it",
    }),
    event(12, "node_completed", "review", { completed: ["fast"], cancelled: ["slow"] }),
  ]);

  it("nests each branch under the parallel, with its own steps and status", () => {
    const [review] = timeline.steps;
    expect(timeline.steps.map((s) => s.id)).toEqual(["review"]);
    expect(review!.status).toBe("completed");
    expect(review!.branches?.map((b) => [b.index, b.id, b.status])).toEqual([
      [0, "fast", "completed"],
      [1, "slow", "cancelled"],
    ]);
    expect(review!.branches?.[0]!.steps.map((s) => [s.id, s.status])).toEqual([
      ["fast", "completed"],
    ]);
    expect(messages(review!.branches![0]!.steps[0]!).map((m) => m.text)).toEqual(["first"]);
    expect(review!.branches?.[1]!.steps.map((s) => [s.id, s.status])).toEqual([
      ["slow", "cancelled"],
    ]);
  });
});

describe("the run's clock", () => {
  const T0 = Date.UTC(2026, 9, 27, 9, 0, 0);
  /** `[type, seconds after T0]` as events in order; a gate event is the gate node's. */
  function timed(...rows: [string, number][]): RunEvent[] {
    return rows.map(([type, seconds], i) => ({
      ...event(i + 1, type, type.startsWith("run_") ? null : "gate"),
      created_at: new Date(T0 + seconds * 1000).toISOString(),
    }));
  }

  it("keeps a run's active and waiting time apart (Done when, 11.2)", () => {
    const timeline = buildTimeline(
      timed(
        ["run_started", 0],
        ["node_started", 30],
        ["gate_waiting", 60],
        ["run_resumed", 3660],
        ["gate_decided", 3661],
        ["run_completed", 3720],
      ),
    );

    expect(clockAt(timeline.clock, T0 + 99_999_000)).toEqual({
      activeMs: 120_000,
      waitingMs: 3_600_000,
    });
  });

  it("counts the open stretch up to now", () => {
    const working = buildTimeline(timed(["run_started", 0], ["node_started", 5]));
    expect(clockAt(working.clock, T0 + 9_000)).toEqual({ activeMs: 9_000, waitingMs: 0 });

    const waiting = buildTimeline(timed(["run_started", 0], ["gate_waiting", 60]));
    expect(clockAt(waiting.clock, T0 + 360_000)).toEqual({ activeMs: 60_000, waitingMs: 300_000 });
  });

  it("counts a cut-off attempt until its last event, not the gap before the next", () => {
    const timeline = buildTimeline(
      timed(["run_started", 0], ["node_started", 10], ["run_resumed", 600], ["run_completed", 605]),
    );
    expect(clockAt(timeline.clock, T0)).toEqual({ activeMs: 15_000, waitingMs: 0 });
  });

  it("has no active time before the run starts", () => {
    expect(clockAt(buildTimeline([]).clock, T0)).toEqual({ activeMs: null, waitingMs: 0 });
  });
});
