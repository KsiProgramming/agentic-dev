import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { WorkflowSpec } from "../graph/spec-graph";
import { runEvent } from "../testing";
import { buildTimeline, type ToolTurn } from "../timeline";
import { parseRepoDiff } from "./parse-diff";
import { stepEntries, stepRows } from "./step-entries";
import { StepInput } from "./step-input";
import { ToolCallRow } from "./tool-calls";
import { describeTool, summarizeTools } from "./tool-describe";
import { UnifiedDiff } from "./unified-diff";

/** What `repo.diff` returns (tech-stack → Tool layer). */
const DIFF = [
  "test_writer changed 3 files (+3 -1) against the run's base 1234567:",
  "modified src/price.py (+2 -1)",
  "added tests/test_price.py (+1 -0)",
  "renamed old.py -> new.py (+0 -0)",
  "added logo.png (binary, not shown)",
  "",
  "diff --git a/src/price.py b/src/price.py",
  "index 111..222 100644",
  "--- a/src/price.py",
  "+++ b/src/price.py",
  "@@ -3,2 +3,3 @@ def parse_price(text):",
  " keep",
  "-    return float(text)",
  "+    value = float(text)",
  "+    return round(value, 2)",
  "diff --git a/tests/test_price.py b/tests/test_price.py",
  "new file mode 100644",
  "--- /dev/null",
  "+++ b/tests/test_price.py",
  "@@ -0,0 +1 @@",
  "+def test_price(): <b>not markup</b>",
  "diff --git a/old.py b/new.py",
  "similarity index 100%",
  "rename from old.py",
  "rename to new.py",
  "diff --git a/logo.png b/logo.png",
  "new file mode 100644",
  "Binary files /dev/null and b/logo.png differ",
].join("\n");

function tool(overrides: Partial<ToolTurn> = {}): ToolTurn {
  return {
    kind: "tool",
    key: 1,
    callId: "c1",
    name: "repo.diff",
    arguments: { node: "test_writer" },
    intent: null,
    output: DIFF,
    status: "completed",
    startedAt: "2026-10-22T12:00:00Z",
    endedAt: "2026-10-22T12:00:02Z",
    ...overrides,
  };
}

describe("parseRepoDiff", () => {
  it("reads the file list and each file's hunks with their line numbers", () => {
    const parsed = parseRepoDiff(DIFF);
    expect(parsed?.files.map((f) => [f.status, f.path, f.added, f.removed])).toEqual([
      ["modified", "src/price.py", 2, 1],
      ["added", "tests/test_price.py", 1, 0],
      ["renamed", "new.py", 0, 0],
      ["added", "logo.png", null, null],
    ]);
    expect(parsed?.files[2]?.oldPath).toBe("old.py");
    const price = parsed?.sections.find((s) => s.path === "src/price.py");
    expect(price?.lines.map((l) => [l.kind, l.text, l.oldLine, l.newLine])).toEqual([
      ["hunk", "@@ -3,2 +3,3 @@ def parse_price(text):", null, null],
      ["context", "keep", 3, 3],
      ["removed", "    return float(text)", 4, null],
      ["added", "    value = float(text)", null, 4],
      ["added", "    return round(value, 2)", null, 5],
    ]);
    expect(parsed?.sections.find((s) => s.path === "logo.png")?.lines).toEqual([
      { kind: "note", text: "Binary file, not shown", oldLine: null, newLine: null },
    ]);
    expect(parsed?.truncated).toBeNull();
  });

  it("keeps the note of a cut diff", () => {
    const cut = `${DIFF}\n(truncated at 256 KB: call again with path to read one file)`;
    expect(parseRepoDiff(cut)?.truncated).toBe(
      "truncated at 256 KB: call again with path to read one file",
    );
  });

  it("is null for anything that is not a diff: an error, a refusal, nothing changed", () => {
    expect(parseRepoDiff("Error executing tool diff: writer 'x' has no commits")).toBeNull();
    expect(parseRepoDiff("test_writer changed nothing in the files asked for")).toBeNull();
    expect(parseRepoDiff("")).toBeNull();
  });
});

describe("UnifiedDiff", () => {
  it("keeps the + and − markers, so colour is never the only cue", () => {
    const { container } = render(<UnifiedDiff text={DIFF} label="repo.diff result" />);
    const added = container.querySelectorAll('[data-kind="added"]');
    const removed = container.querySelectorAll('[data-kind="removed"]');
    expect(added).toHaveLength(3);
    expect(removed).toHaveLength(1);
    expect(removed[0]?.textContent).toContain("−");
    expect(added[0]?.textContent).toContain("+");
    // Screen readers are told what each line is.
    expect(removed[0]?.textContent).toContain("Removed: ");
  });

  it("shows each file under a header with its status, path and counts", () => {
    render(<UnifiedDiff text={DIFF} label="repo.diff result" />);
    const file = screen.getByRole("region", { name: "src/price.py" });
    expect(within(file).getByText("Modified")).toBeTruthy();
    expect(within(file).getByText("+2")).toBeTruthy();
    expect(within(file).getByText("−1")).toBeTruthy();
    const renamed = screen.getByRole("region", { name: "new.py" });
    expect(renamed.textContent).toContain("from old.py");
    expect(
      within(screen.getByRole("region", { name: "logo.png" })).getByText("binary"),
    ).toBeTruthy();
  });

  it("shows repo content as text, never as markup", () => {
    const { container } = render(<UnifiedDiff text={DIFF} label="repo.diff result" />);
    expect(container.querySelector("b")).toBeNull();
    expect(container.textContent).toContain("<b>not markup</b>");
  });

  it("scrolls in its own box and is capped with Show full output when long", () => {
    const lines = Array.from({ length: 60 }, (_, i) => `+line ${i}`);
    const long = [
      "w changed 1 file (+60 -0) against the run's base abcdef0:",
      "added big.txt (+60 -0)",
      "",
      "diff --git a/big.txt b/big.txt",
      "@@ -0,0 +1,60 @@",
      ...lines,
    ].join("\n");
    render(<UnifiedDiff text={long} label="repo.diff result" />);
    const box = screen.getByRole("group", { name: "repo.diff result" });
    expect(box.dataset.capped).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Show full output" }));
    expect(box.dataset.capped).toBeUndefined();
    expect(screen.getByRole("button", { name: "Show less" })).toBeTruthy();
  });

  it("says when the diff was cut", () => {
    const cut = `${DIFF}\n(truncated at 256 KB: call again with path to read one file)`;
    render(<UnifiedDiff text={cut} label="repo.diff result" />);
    expect(screen.getByText(/Truncated at 256 KB: call again with path/)).toBeTruthy();
  });

  it("shows an error result as plain text", () => {
    render(<UnifiedDiff text="writer 'x' has no commits" label="repo.diff result" />);
    expect(screen.getByLabelText("repo.diff result").textContent).toBe("writer 'x' has no commits");
    expect(document.querySelector('[data-slot="unified-diff"]')).toBeNull();
  });
});

describe("a repo.diff call in the Activity tab", () => {
  it("draws its result as a diff once opened", () => {
    render(
      <ul>
        <ToolCallRow turn={tool()} />
      </ul>,
    );
    expect(screen.getByRole("button", { name: /Read the changes of test_writer/ })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Read the changes of test_writer/ }));
    expect(document.querySelector('[data-slot="unified-diff"]')).not.toBeNull();
  });

  it("shows a failed call's text as it is", () => {
    render(
      <ul>
        <ToolCallRow
          turn={tool({ status: "failed", output: "writer 'test_writer' has no commits" })}
        />
      </ul>,
    );
    fireEvent.click(screen.getByRole("button", { name: /failed/ }));
    expect(document.querySelector('[data-slot="unified-diff"]')).toBeNull();
    expect(screen.getByLabelText("repo.diff result").textContent).toBe(
      "writer 'test_writer' has no commits",
    );
  });
});

describe("one-liners that name the writer", () => {
  it("says whose changes a repo.diff reads", () => {
    expect(describeTool("repo.diff", { node: "test_writer" })).toMatchObject({
      done: "Read the changes of",
      doing: "Reading the changes of",
      target: "test_writer",
    });
    expect(describeTool("repo.diff", { node: "w", path: "src/a.py" }).suffix).toBe("in src/a.py");
  });

  it("says a file was read as a writer left it", () => {
    expect(describeTool("repo.read_file", { path: "src/a.py", node: "test_writer" })).toMatchObject(
      {
        done: "Read",
        target: "src/a.py",
        suffix: "as test_writer left it",
      },
    );
    expect(describeTool("repo.read_file", { path: "src/a.py" }).suffix).toBeUndefined();
    expect(describeTool("repo.list_files", { node: "w" }).suffix).toBe("as w left it");
    expect(describeTool("repo.search", { pattern: "x", node: "w" }).suffix).toBe("as w left it");
  });

  it("shows the sentence on the call's line", () => {
    render(
      <ul>
        <ToolCallRow
          turn={tool({
            name: "repo.read_file",
            arguments: { path: "src/a.py", node: "test_writer" },
            output: "1\tx = 1",
          })}
        />
      </ul>,
    );
    expect(
      screen.getByRole("button", { name: /Read src\/a\.py as test_writer left it/ }),
    ).toBeTruthy();
  });

  it("counts diffs in a group summary", () => {
    expect(summarizeTools([tool(), tool({ key: 2 })])).toBe("Read 2 diffs");
  });
});

describe("the Input tab lists the writers a step was told about", () => {
  const spec: WorkflowSpec = {
    spec_version: "0",
    id: "review",
    name: "Review",
    root: {
      type: "agent",
      id: "reviewer",
      role: "Reviewer",
      instructions: "Review.",
      tools: ["repo.diff"],
    },
  };

  function rowFor(writers: unknown) {
    const timeline = buildTimeline([
      runEvent(1, "run_started"),
      {
        ...runEvent(2, "node_started", writers === undefined ? {} : { writers }),
        node_id: "reviewer",
      },
    ]);
    const [row] = stepRows(stepEntries(timeline.steps));
    if (!row) throw new Error("no row");
    return { row, timeline };
  }

  it("keeps node_started's writers on the step", () => {
    const { timeline } = rowFor([
      { node_id: "test_writer", kind: "writer" },
      { node_id: "build", kind: "integration" },
      { nope: 1 },
    ]);
    expect(timeline.steps[0]?.writers).toEqual([
      { nodeId: "test_writer", kind: "writer" },
      { nodeId: "build", kind: "integration" },
    ]);
    expect(rowFor([]).timeline.steps[0]?.writers).toEqual([]);
    expect(rowFor(undefined).timeline.steps[0]?.writers).toBeNull();
  });

  it("shows each writer's id in the mono font with its kind", () => {
    const { row } = rowFor([
      { node_id: "test_writer", kind: "writer" },
      { node_id: "build", kind: "integration" },
    ]);
    render(<StepInput runId="run-1" row={row} spec={spec} runInput={null} first={false} />);
    expect(screen.getByText("Work before this step")).toBeTruthy();
    const writer = screen.getByText("test_writer");
    expect(writer.className).toContain("font-mono");
    expect(writer.parentElement?.textContent).toContain("writer");
    expect(screen.getByText("build").parentElement?.textContent).toContain("team's merged work");
  });

  it("shows nothing for the first writer or a step that was told nothing", () => {
    for (const writers of [[], undefined]) {
      const { row } = rowFor(writers);
      const { unmount } = render(
        <StepInput runId="run-1" row={row} spec={spec} runInput={null} first={false} />,
      );
      expect(screen.queryByText("Work before this step")).toBeNull();
      unmount();
    }
  });
});
