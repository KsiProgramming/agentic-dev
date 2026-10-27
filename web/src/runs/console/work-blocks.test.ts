import { describe, expect, it } from "vitest";

import docsRun from "../fixtures/docs-run.json";
import { runEvent } from "../testing";
import { buildTimeline, type Step } from "../timeline";
import type { RunEvent } from "../types";
import { currentActivity } from "./activity";
import { lastMessage } from "./step-entries";
import { agentTurns, currentTitle, mapTotals, workStart, workSummary } from "./work-blocks";

type Ev = [type: string, payload?: RunEvent["payload"]];

/** The events of one agent step `w`, one second apart from second 1. */
function events(list: Ev[], end = true): RunEvent[] {
  const all: Ev[] = [["node_started"], ...list, ...(end ? [["node_completed"] as Ev] : [])];
  return all.map(([type, payload], i) => ({ ...runEvent(i + 1, type, payload), node_id: "w" }));
}

const step = (list: Ev[], end = true): Step => buildTimeline(events(list, end)).steps[0]!;

const call = (id: string, name: string, args: Record<string, unknown> = {}): Ev => [
  "tool_call",
  { call_id: id, name, arguments: args },
];
const result = (id: string, isError = false): Ev => [
  "tool_result",
  { call_id: id, output: "ok", is_error: isError },
];

const kinds = (s: Step) =>
  agentTurns(s).map((t) => ({
    work: t.work.map((r) => (r.kind === "tools" ? `tools×${r.turns.length}` : r.kind)),
    answer: t.answer?.text ?? null,
  }));

describe("agentTurns", () => {
  it("splits the recorded writer into its work and its answer", () => {
    const writer = buildTimeline(docsRun as RunEvent[]).steps[1]!.items![0]!.steps[0]!;
    expect(kinds(writer)).toEqual([
      {
        work: ["reasoning", "note", "tool", "tools×2"],
        answer: expect.stringContaining("# packages/api"),
      },
    ]);
  });

  it("folds reads with no intent, and keeps intents, writes and failures on their own", () => {
    const s = step([
      call("a", "repo.read_file", { path: "a" }),
      result("a"),
      call("b", "repo.search", { pattern: "x" }),
      result("b"),
      call("c", "repo.read_file", { path: "c", description: "Read the config" }),
      result("c"),
      call("d", "repo.list_files", { path: "." }),
      result("d", true),
      call("e", "repo.write_file", { path: "e", content: "hi" }),
      result("e"),
      call("f", "repo.read_file", { path: "f" }),
      result("f"),
      ["message", { text: "Done." }],
    ]);
    expect(kinds(s)).toEqual([
      { work: ["tools×2", "tool", "tool", "tool", "tools×1"], answer: "Done." },
    ]);
  });

  it("calls text followed by more work a note, and the text a step ends on its answer", () => {
    const live = step(
      [["text_delta", { text: "Let me look." }], call("a", "repo.read_file"), result("a")],
      false,
    );
    expect(kinds(live)).toEqual([{ work: ["note", "tools×1"], answer: null }]);
    expect(lastMessage(live)).toBeNull();

    const answering = step([["text_delta", { text: "It is" }]], false);
    expect(kinds(answering)).toEqual([{ work: [], answer: "It is" }]);
    expect(lastMessage(answering)?.text).toBe("It is");
  });

  it("leaves a step that failed before answering with work and no answer", () => {
    const s = step([call("a", "repo.read_file"), result("a", true), ["failed", { error: "x" }]]);
    expect(kinds(s)).toEqual([{ work: ["tool"], answer: null }]);
  });
});

describe("workSummary", () => {
  it("says what was done, how many calls, and from the step's start to the last result", () => {
    // Started at second 1; the last result at second 5.
    const s = step([
      call("a", "repo.list_files", { path: "." }),
      result("a"),
      call("b", "repo.read_file", { path: "b" }),
      result("b"),
      ["message", { text: "Done." }],
    ]);
    const [turn] = agentTurns(s);
    expect(workSummary(turn!.work, workStart(s, turn!, 0))).toEqual({
      text: "Listed 1 folder, read 1 file",
      toolCalls: 2,
      failed: 0,
      ms: 4000,
    });
  });

  it("calls reasoning with no calls thinking it through", () => {
    const s = step([
      ["reasoning_delta", { text: "Hm." }],
      ["message", { text: "Yes." }],
    ]);
    const [turn] = agentTurns(s);
    expect(workSummary(turn!.work, s.startedAt)).toMatchObject({
      text: "Thought it through",
      toolCalls: 0,
      ms: null,
    });
  });
});

describe("currentTitle and the live line", () => {
  it("says the running call's intent, else what it does, else Thinking", () => {
    const withIntent = step(
      [call("a", "repo.read_file", { path: "a", description: "Read it" })],
      false,
    );
    expect(currentTitle(agentTurns(withIntent)[0]!.work)).toEqual({ text: "Read it", target: "" });
    expect(
      currentActivity(
        buildTimeline(
          events([call("a", "repo.read_file", { path: "a", description: "Read it" })], false),
        ),
      ),
    ).toMatchObject({
      doing: "Read it",
      target: "",
    });

    const without = step([call("a", "repo.read_file", { path: "src/a.ts" })], false);
    expect(currentTitle(agentTurns(without)[0]!.work)).toEqual({
      text: "Reading",
      target: "src/a.ts",
    });

    const thinking = step([["reasoning_delta", { text: "Hm" }]], false);
    expect(currentTitle(agentTurns(thinking)[0]!.work)).toEqual({ text: "Thinking", target: "" });
  });
});

describe("mapTotals", () => {
  it("adds up a map's items: how many, their calls, first start to last end", () => {
    const map = buildTimeline(docsRun as RunEvent[]).steps[1]!;
    const totals = mapTotals(map);
    expect(totals.items).toBe(3);
    expect(totals.toolCalls).toBe(9);
    expect(totals.ms).not.toBeNull();
  });

  it("has no time while an item still runs", () => {
    const all = docsRun as RunEvent[];
    const firstDone = all.find((e) => e.type === "map_item_completed")!.seq;
    const events = all.filter((e) => e.seq < firstDone);
    expect(mapTotals(buildTimeline(events).steps[1]!).ms).toBeNull();
  });
});
