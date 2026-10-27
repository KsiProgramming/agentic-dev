import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { JsonView } from "@/components/json-view";

import docsRun from "../fixtures/docs-run.json";
import { runEvent } from "../testing";
import { buildTimeline, type ToolTurn } from "../timeline";
import type { RunEvent } from "../types";
import { currentActivity } from "./activity";
import { AgentMessage } from "./agent-message";
import { StepList } from "./step-view";
import { ToolCallGroup, ToolCallRow } from "./tool-calls";
import { describeTool, summarizeTools } from "./tool-describe";

const NOW = Date.parse("2026-10-22T12:00:00Z");

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AgentMessage", () => {
  it("renders Markdown", () => {
    render(<AgentMessage text={"# Title\n\nSome **bold** text.\n\n- one\n- two"} />);
    expect(screen.getByRole("heading", { name: "Title" })).toBeTruthy();
    expect(screen.getByText("bold").tagName).toBe("STRONG");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("drops raw HTML and comments, never rendering them", () => {
    const { container } = render(
      <AgentMessage
        text={
          '<!-- module: src -->\nHi <script>alert(1)</script> <img src=x onerror="alert(2)"> there'
        }
      />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).not.toContain("module: src");
    expect(container.textContent).toContain("Hi");
  });

  it("drops Markdown images, so no remote URL is fetched", () => {
    const { container } = render(<AgentMessage text="![x](https://evil.example/?q=secret)" />);
    expect(container.querySelector("img")).toBeNull();
  });

  it("opens links in a new tab and drops javascript: URLs", () => {
    render(<AgentMessage text="[docs](https://example.com) and [bad](javascript:alert(1))" />);
    const docs = screen.getByRole("link", { name: "docs" });
    expect(docs.getAttribute("target")).toBe("_blank");
    expect(docs.getAttribute("rel")).toBe("noreferrer");
    expect(screen.getByText("bad").getAttribute("href") ?? "").not.toContain("javascript");
  });

  it("shows a caret only while streaming", () => {
    const { rerender } = render(<AgentMessage text="Hello" streaming />);
    expect(screen.getByTestId("agent-message").dataset.streaming).toBe("true");
    rerender(<AgentMessage text="Hello" />);
    expect(screen.getByTestId("agent-message").dataset.streaming).toBeUndefined();
  });
});

describe("JsonView", () => {
  it("opens the first two levels and collapses deeper ones", () => {
    const { container } = render(<JsonView value={{ a: { b: { c: 1 } } }} />);
    const levels = container.querySelectorAll("details");
    expect([...levels].map((d) => d.open)).toEqual([true, true, false]);
  });

  it("copies the pretty-printed JSON", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    render(<JsonView value={{ path: "src" }} label="arguments" />);
    fireEvent.click(screen.getByRole("button", { name: "Copy arguments" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('{\n  "path": "src"\n}'));
  });
});

function tool(overrides: Partial<ToolTurn> = {}): ToolTurn {
  return {
    kind: "tool",
    key: 1,
    callId: "c1",
    name: "repo.read_file",
    arguments: { path: "src/app.ts" },
    output: '{"text": "x"}',
    status: "completed",
    startedAt: "2026-10-22T12:00:00Z",
    endedAt: "2026-10-22T12:00:02Z",
    ...overrides,
  };
}

describe("describeTool", () => {
  it("says what each repo tool did, and what it is doing", () => {
    expect(describeTool("repo.read_file", { path: "a.ts" })).toMatchObject({
      done: "Read",
      doing: "Reading",
      target: "a.ts",
    });
    expect(describeTool("repo.list_files", { path: "." }).target).toBe("repository root");
    expect(describeTool("repo.search", { pattern: "Item" })).toMatchObject({
      done: "Searched for",
      target: "Item",
    });
    expect(describeTool("repo.commit", { message: "docs: add\n\nbody" }).target).toBe("docs: add");
    expect(describeTool("custom.tool", { q: "x" })).toMatchObject({
      done: "Called custom.tool",
      target: "x",
    });
  });

  it("sums up a group of calls", () => {
    const turns = [
      tool(),
      tool({ key: 2 }),
      tool({ key: 3, name: "repo.list_files", arguments: { path: "src" } }),
      tool({ key: 4, name: "repo.search", arguments: { pattern: "x" } }),
    ];
    expect(summarizeTools(turns)).toBe("Read 2 files, listed 1 folder, ran 1 search");
  });
});

describe("ToolCallRow", () => {
  it("is one line until opened, then shows the arguments and the result", () => {
    render(
      <ul>
        <ToolCallRow turn={tool()} />
      </ul>,
    );
    const trigger = screen.getByRole("button", { name: /Read src\/app\.ts/ });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("Arguments")).toBeNull();
    fireEvent.click(trigger);
    expect(screen.getByRole("group", { name: "repo.read_file arguments" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "repo.read_file result" }).textContent).toContain(
      '"x"',
    );
  });

  it("marks a failed call and shows its plain-text output", () => {
    render(
      <ul>
        <ToolCallRow turn={tool({ output: "no such file", status: "failed" })} />
      </ul>,
    );
    expect(screen.getByTestId("tool-call").dataset.status).toBe("failed");
    const trigger = screen.getByRole("button", { name: /Read src\/app\.ts failed/ });
    fireEvent.click(trigger);
    expect(screen.getByLabelText("repo.read_file result").textContent).toBe("no such file");
  });

  it("says what a call in flight is doing", () => {
    render(
      <ul>
        <ToolCallRow turn={tool({ status: "running", output: null, endedAt: null })} />
      </ul>,
    );
    expect(screen.getByRole("button").textContent).toContain("Reading");
  });
});

describe("ToolCallGroup", () => {
  const turns = [
    tool(),
    tool({ key: 2, arguments: { path: "src/b.ts" }, endedAt: "2026-10-22T12:00:05Z" }),
    tool({ key: 3, name: "repo.list_files", arguments: { path: "src" }, status: "failed" }),
  ];

  it("collapses consecutive calls into one summary line", () => {
    render(<ToolCallGroup turns={turns} />);
    const summary = screen.getByRole("button", { name: /Read 2 files, listed 1 folder/ });
    expect(summary.textContent).toContain("1 failed");
    expect(summary.textContent).toContain("3 tool calls");
    expect(screen.queryAllByTestId("tool-call")).toHaveLength(0);
    fireEvent.click(summary);
    expect(screen.getAllByTestId("tool-call")).toHaveLength(3);
  });

  it("shows the call in flight while the group runs", () => {
    render(
      <ToolCallGroup
        turns={[
          tool(),
          tool({
            key: 2,
            arguments: { path: "src/b.ts" },
            status: "running",
            output: null,
            endedAt: null,
          }),
        ]}
      />,
    );
    expect(screen.getByRole("button").textContent).toContain("Reading src/b.ts…");
  });
});

describe("StepList on the recorded docs run", () => {
  const timeline = buildTimeline(docsRun as RunEvent[]);

  it("shows one message block per agent turn, nested under the map items", () => {
    render(<StepList steps={timeline.steps} options={{ now: NOW }} />);
    const items = screen.getAllByTestId("map-item");
    expect(items.map((i) => i.querySelector("h4")?.textContent)).toEqual([
      "packages/api",
      "packages/engine",
      "web",
    ]);
    const first = within(items[0]!);
    expect(first.getAllByTestId("agent-message")).toHaveLength(2);
    expect(first.getAllByTestId("tool-group")).toHaveLength(1);
    // A one-step item is not headed twice.
    expect(first.queryByRole("heading", { name: "module-writer" })).toBeNull();
    // 3 writers × 2 turns + 2 review turns.
    expect(screen.getAllByTestId("agent-message")).toHaveLength(8);
    // The page's Markdown heading renders inside the second message.
    const page = within(first.getAllByTestId("agent-message")[1]!);
    expect(page.getByRole("heading", { name: "packages/api" })).toBeTruthy();
  });

  it("shows loop iterations, usage and the gate decision", () => {
    render(<StepList steps={timeline.steps} options={{ now: NOW }} />);
    expect(
      screen.getAllByTestId("iteration").map((i) => i.querySelector("p")?.textContent),
    ).toEqual(["Iteration 1· condition not met", "Iteration 2· condition met"]);
    expect(screen.getAllByTestId("usage")[0]?.textContent).toBe(
      "1.2K in · 180 out · — (Some usage was logged before costs were tracked.)",
    );
    expect(screen.getByText("Open the docs PR?").parentElement?.textContent).toContain("Approved");
  });

  it("renders extra content for a step", () => {
    render(
      <StepList
        steps={timeline.steps}
        options={{ now: NOW, extra: (s) => (s.id === "approve" ? <p>gate panel</p> : null) }}
      />,
    );
    const gate = screen.getAllByTestId("step").find((s) => s.dataset.nodeId === "approve")!;
    expect(within(gate).getByText("gate panel")).toBeTruthy();
  });

  it("shows a gate's time as time waited, not as a duration", () => {
    render(<StepList steps={timeline.steps} options={{ now: NOW }} />);
    const gate = screen.getAllByTestId("step").find((s) => s.dataset.nodeId === "approve")!;
    expect(within(gate).getByTestId("gate-waited").textContent).toMatch(/^waited /);
  });
});

describe("previews and the rail", () => {
  const write = tool({
    key: 5,
    name: "repo.write_file",
    arguments: { path: "docs/a.md", content: "# A\n\nline 2\nline 3\nline 4\nline 5\nline 6" },
  });

  it("previews what a write wrote, and how much more there is", () => {
    render(
      <ul>
        <ToolCallRow turn={write} />
      </ul>,
    );
    const preview = screen.getByTestId("tool-preview");
    expect(preview.querySelector("pre")?.textContent).toBe("# A\n\nline 2\nline 3");
    expect(preview.textContent).toContain("+3 more lines");
  });

  it("previews a failure's error, and nothing for a quiet read", () => {
    render(
      <ul>
        <ToolCallRow turn={tool({ status: "failed", output: "no such file" })} />
        <ToolCallRow turn={tool({ key: 2 })} />
      </ul>,
    );
    expect(screen.getAllByTestId("tool-preview").map((p) => p.textContent)).toEqual([
      "no such file",
    ]);
  });

  it("keeps a write on its own line instead of in a group of reads", () => {
    const steps = buildTimeline([
      { ...runEvent(1, "node_started"), node_id: "w" },
      ...[2, 3].flatMap((seq) => [
        {
          ...runEvent(seq * 2, "tool_call", {
            call_id: `r${seq}`,
            name: "repo.read_file",
            arguments: { path: `f${seq}` },
          }),
          node_id: "w",
        },
        {
          ...runEvent(seq * 2 + 1, "tool_result", { call_id: `r${seq}`, output: "x" }),
          node_id: "w",
        },
      ]),
      {
        ...runEvent(8, "tool_call", {
          call_id: "w1",
          name: "repo.write_file",
          arguments: { path: "a.md", content: "hi" },
        }),
        node_id: "w",
      },
      { ...runEvent(9, "tool_result", { call_id: "w1", output: "ok" }), node_id: "w" },
    ]).steps;
    render(<StepList steps={steps} options={{ now: NOW }} />);
    const groups = screen.getAllByTestId("tool-group");
    expect(groups.map((g) => g.textContent?.includes("Read 2 files"))).toEqual([true, false]);
    expect(screen.getByTestId("tool-preview").textContent).toBe("hi");
  });

  it("marks each step's status with an icon and a label for screen readers", () => {
    const timeline = buildTimeline(docsRun as RunEvent[]);
    render(<StepList steps={timeline.steps} options={{ now: NOW }} />);
    const first = screen.getAllByTestId("step")[0]!;
    expect(first.querySelector(".sr-only")?.textContent).toBe("Done");
  });
});

describe("currentActivity", () => {
  it("says what the latest running step is doing", () => {
    const timeline = buildTimeline([
      { ...runEvent(1, "node_started"), node_id: "writer" },
      {
        ...runEvent(2, "tool_call", {
          call_id: "c",
          name: "repo.read_file",
          arguments: { path: "a.ts" },
        }),
        node_id: "writer",
      },
    ]);
    expect(currentActivity(timeline)).toEqual({
      where: "writer",
      doing: "Reading",
      target: "a.ts",
      running: 1,
    });
  });

  it("names a map item by its path and counts what runs at once", () => {
    const timeline = buildTimeline([
      { ...runEvent(1, "node_started"), node_id: "document" },
      {
        ...runEvent(2, "map_item_started", { index: 0, item: { path: "src/a" } }),
        node_id: "document",
      },
      { ...runEvent(3, "node_started", { item: 0 }), node_id: "w" },
      {
        ...runEvent(4, "map_item_started", { index: 1, item: { path: "src/b" } }),
        node_id: "document",
      },
      { ...runEvent(5, "node_started", { item: 1 }), node_id: "w" },
      { ...runEvent(6, "text_delta", { text: "Hi", item: 1 }), node_id: "w" },
    ]);
    expect(currentActivity(timeline)).toMatchObject({
      where: "src/b",
      doing: "Writing",
      running: 2,
    });
  });

  it("is null once nothing runs", () => {
    expect(currentActivity(buildTimeline(docsRun as RunEvent[]))).toBeNull();
  });
});
