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

describe("stepOutline of a merging reduce (4.5)", () => {
  it("says how many findings it merged into how many, from how many sources", () => {
    const events = [
      runEvent(1, "node_started"),
      runEvent(2, "node_completed", {
        merged: { sources: 3, findings_in: 42, findings_out: 30 },
      }),
    ].map((e) => ({ ...e, node_id: "merge" }));
    const [row] = stepRows(stepEntries(buildTimeline(events).steps));

    expect(stepOutline(row!.step)).toBe("Merged 42 findings into 30 from 3 sources");
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

describe("routers (4.6)", () => {
  const ROUTED: WorkflowSpec = {
    spec_version: "0",
    id: "routed",
    name: "Routed",
    root: {
      type: "sequence",
      id: "main",
      steps: [
        {
          type: "router",
          id: "report_path",
          routes: [
            {
              id: "clean",
              when: "false",
              then: { type: "agent", id: "clean_report", role: "W", instructions: "Go." },
            },
          ],
          default: { type: "agent", id: "standard_report", role: "W", instructions: "Go." },
        },
        { type: "agent", id: "after", role: "W", instructions: "Go." },
      ],
    },
  } as WorkflowSpec;
  const events = [
    on("report_path", runEvent(1, "node_started", { routes: ["clean", "default"], mode: "rule" })),
    on(
      "report_path",
      runEvent(2, "route_chosen", { route: "default", reason: "no route matched" }),
    ),
    on("standard_report", runEvent(3, "node_started")),
    on("standard_report", runEvent(4, "message", { text: "# Audit\n\nAll good." })),
    on("standard_report", runEvent(5, "node_completed")),
    on("report_path", runEvent(6, "node_completed", { route: "default" })),
  ];

  it("nests the route's steps under the router and says where it went", () => {
    const steps = buildTimeline(events).steps;
    const entries = stepEntries(steps);

    expect(stepRows(entries).map((r) => [r.key, r.depth])).toEqual([
      ["report_path", 0],
      ["report_path>default/standard_report", 1],
    ]);
    expect(stepOutline(steps[0]!)).toBe("Routed to default");
    expect(stepOutline(buildTimeline(events.slice(0, 1)).steps[0]!)).toBe("Choosing a route");
    // The router is a container: the step that did the work is its route's.
    expect(defaultEntry(entries, false)?.key).toBe("report_path>default/standard_report");
  });

  it("leaves the routes not taken out of the run's progress", () => {
    const progress = stepsProgress(ROUTED, buildTimeline(events).steps);

    expect(progress).toMatchObject({ total: 3, done: 2, running: 0 });
  });
});

describe("stepOutline of scans and reviews", () => {
  const report = (scanner: string, checks: object[], counts: object) =>
    JSON.stringify({ scanner, checks, findings: [], counts });
  const ran = (path: string) => ({ path, kind: "python", tool: "ruff", status: "ran" });
  const outline = (events: RunEvent[]) =>
    stepOutline(stepRows(stepEntries(buildTimeline(events).steps))[0]!.step);
  const tool = (node: string, output: string): RunEvent[] => [
    on(node, runEvent(1, "node_started")),
    on(
      node,
      runEvent(2, "tool_call", { call_id: "c1", name: "scan.lint", arguments: { path: "." } }),
    ),
    on(node, runEvent(3, "tool_result", { call_id: "c1", output })),
    on(node, runEvent(4, "node_completed")),
  ];

  it("says what a scan found, so two scans of the repo read differently", () => {
    expect(outline(tool("lint", report("lint", [ran("a"), ran("b")], { medium: 2 })))).toBe(
      "Linted 2 modules · 2 findings",
    );
    expect(outline(tool("secrets", report("secrets", [ran(".")], {})))).toBe(
      "Scanned for secrets · no findings",
    );
  });

  it("says when every module was skipped, and why", () => {
    const skipped = { path: "src", kind: "dotnet", tool: null, status: "skipped" };
    const reason = { ...skipped, reason: "no supported linter for dotnet" };
    expect(outline(tool("lint", report("lint", [reason, skipped], {})))).toBe(
      "Skipped 2 modules: no supported linter for dotnet",
    );
  });

  it("reads an agent's findings answer, not its first JSON line", () => {
    const answer = "```json\n" + report("agent", [ran(".")], { high: 1, low: 2 }) + "\n```";
    expect(
      outline([
        on("security_1", runEvent(1, "node_started")),
        on("security_1", runEvent(2, "message", { text: answer })),
      ]),
    ).toBe("Answered with 3 findings");
    expect(
      outline([
        on("pick", runEvent(1, "node_started")),
        on("pick", runEvent(2, "message", { text: '{"route": "fix"}' })),
      ]),
    ).toBe("Answered in JSON");
  });
});
