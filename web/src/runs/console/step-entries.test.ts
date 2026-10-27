import { describe, expect, it } from "vitest";

import docsRun from "../fixtures/docs-run.json";
import docsSpec from "../fixtures/docs-run-spec.json";
import type { WorkflowSpec } from "../graph/spec-graph";
import { nodeStatuses } from "../graph/node-status";
import { runEvent } from "../testing";
import { buildTimeline } from "../timeline";
import type { RunEvent } from "../types";
import { rowOffsetMs, rowSummary } from "./event-rows";
import { stepsProgress } from "./run-stats";
import {
  defaultEntry,
  failingEntry,
  findEntry,
  stepEntries,
  stepOutline,
  stepRows,
} from "./step-entries";
import { fileKind, writtenFiles } from "./written-files";
import { foldDeltas } from "../timeline";

const docs = docsRun as RunEvent[];

function on(node: string, event: RunEvent): RunEvent {
  return { ...event, node_id: node };
}

/** `docs` up to and with event `seq`. */
function upTo(seq: number) {
  return stepEntries(buildTimeline(docs.filter((e) => e.seq <= seq)).steps);
}

describe("stepEntries", () => {
  it("keys each step by its node and scope, stable as the run grows", () => {
    const early = upTo(25).map((e) => e.key);
    const all = stepEntries(buildTimeline(docs).steps).map((e) => e.key);
    expect(all.slice(0, early.length)).toEqual(early);
    expect(findEntry(stepEntries(buildTimeline(docs).steps), "revise#2/reviewer")?.name).toBe(
      "Iteration 2",
    );
    expect(findEntry(stepEntries(buildTimeline(docs).steps), "nope")).toBeNull();
  });

  it("keeps the map item a step runs for, for its input", () => {
    const row = findEntry(stepEntries(buildTimeline(docs).steps), "document[1]/module-writer");
    expect(row?.item?.item).toBe("packages/engine");
    expect(row?.depth).toBe(1);
  });

  it("heads a branch with several steps, its steps under it", () => {
    const entries = stepEntries(
      buildTimeline([
        on("checks", runEvent(1, "node_started", { branches: 1 })),
        on("checks", runEvent(2, "parallel_branch_started", { index: 0, branch_id: "lint" })),
        on("a", runEvent(3, "node_started", { branch: 0 })),
        on("a", runEvent(4, "node_completed", { branch: 0 })),
        on("b", runEvent(5, "node_started", { branch: 0 })),
      ]).steps,
    );
    expect(entries.map((e) => [e.kind, e.key, e.depth])).toEqual([
      ["step", "checks", 0],
      ["scope", "checks:lint", 1],
      ["step", "checks:lint/a", 2],
      ["step", "checks:lint/b", 2],
    ]);
  });
});

describe("defaultEntry", () => {
  it("opens a finished run on its last agent's answer", () => {
    expect(defaultEntry(stepEntries(buildTimeline(docs).steps), false)?.key).toBe(
      "revise#2/reviewer",
    );
  });

  it("follows the running step while the run is live", () => {
    expect(defaultEntry(upTo(25), true)?.key).toMatch(/^document\[\d]\/module-writer$/);
  });

  it("shows the gate the run waits at", () => {
    const entries = stepEntries(
      buildTimeline([
        on("w", runEvent(1, "node_started")),
        on("w", runEvent(2, "message", { text: "Done." })),
        on("w", runEvent(3, "node_completed")),
        on("gate", runEvent(4, "gate_waiting", { title: "Open a PR?" })),
      ]).steps,
    );
    expect(defaultEntry(entries, true)?.key).toBe("gate");
  });

  it("shows the step a failed run failed at, the deepest one", () => {
    const entries = stepEntries(
      buildTimeline([
        on("m", runEvent(1, "node_started", { items: 1 })),
        on("m", runEvent(2, "map_item_started", { index: 0, item: "a" })),
        on("w", runEvent(3, "node_started", { item: 0 })),
        on("w", runEvent(4, "node_failed", { item: 0, error: "Boom" })),
        on("m", runEvent(5, "node_failed", { error: "an item failed" })),
        runEvent(6, "run_failed", { error: "Boom" }),
      ]).steps,
    );
    expect(failingEntry(entries)?.key).toBe("m[0]/w");
    expect(defaultEntry(entries, false)?.key).toBe("m[0]/w");
    expect(stepOutline(failingEntry(entries)!.step)).toBe("Boom");
  });

  it("is null before the first step", () => {
    expect(defaultEntry([], true)).toBeNull();
  });
});

describe("stepOutline", () => {
  it("says what each step of the docs run did", () => {
    const rows = stepRows(stepEntries(buildTimeline(docs).steps));
    const outline = (key: string) => stepOutline(rows.find((r) => r.key === key)!.step);
    expect(outline("document")).toBe("3 of 3 items");
    expect(outline("revise")).toBe("2 iterations");
    expect(outline("approve")).toBe("Approved");
    expect(outline("list_modules")).toBe("Found the modules");
    expect(outline("document[0]/module-writer")).toBe("packages/api");
  });
});

describe("writtenFiles", () => {
  it("keeps the last content of each path a step wrote, and skips failed writes", () => {
    const [step] = buildTimeline([
      on("w", runEvent(1, "node_started")),
      ...(
        [
          ["c1", "docs/a.md", "one", false],
          ["c2", "docs/b.ts", "x", false],
          ["c3", "docs/a.md", "two", false],
          ["c4", "docs/c.md", "never", true],
        ] as const
      ).flatMap(([id, path, content, failed], i) => [
        on(
          "w",
          runEvent(2 + i * 2, "tool_call", {
            call_id: id,
            name: "repo.write_file",
            arguments: { path, content },
          }),
        ),
        on(
          "w",
          runEvent(3 + i * 2, "tool_result", { call_id: id, output: "ok", is_error: failed }),
        ),
      ]),
    ]).steps;
    expect(writtenFiles(step!)).toEqual([
      { path: "docs/a.md", kind: "Markdown", content: "two", writes: 2 },
      { path: "docs/b.ts", kind: "TypeScript", content: "x", writes: 1 },
    ]);
    expect(fileKind("Makefile")).toBe("File");
  });
});

describe("stepsProgress", () => {
  it("counts the spec's nodes as the graph does", () => {
    const spec = docsSpec as WorkflowSpec;
    const steps = buildTimeline(docs.filter((e) => e.seq <= 25)).steps;
    const progress = stepsProgress(spec, steps);
    expect(progress.total).toBe(nodeStatuses(spec, steps).size);
    expect(progress).toMatchObject({ total: 7, done: 1, running: 2 });
  });
});

describe("event rows", () => {
  it("say what each event holds in one line, and when it came", () => {
    const rows = foldDeltas([
      runEvent(1, "run_started"),
      runEvent(2, "text_delta", { text: "one\ntwo " }),
      runEvent(3, "text_delta", { text: "three" }),
      runEvent(4, "tool_result", { output: '{"a": 1}' }),
    ]);
    expect(rows.map(rowSummary)).toEqual(["", "one two three", "JSON, 1 entry"]);
    expect(rowOffsetMs(rows[2]!, runEvent(1, "x").created_at)).toBe(3000);
  });
});
