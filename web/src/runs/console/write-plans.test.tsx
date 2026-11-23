import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { parsePlans, parseWriteCheck, type WritePlan } from "../plans";
import { WriteChecked, WritePlans } from "./write-plans";

const API_PLAN = {
  node_id: "publish",
  tool: "github.openPR",
  action: "open_pr",
  summary: "Push 2 commits to agent/9f3/implement and open a pull request into main",
  target: { kind: "repo", label: "acme/shop", url: "https://github.com/acme/shop" },
  fields: {
    repo: "acme/shop",
    head: "agent/9f3/implement",
    base: "main",
    commits: 2,
    title: "Export orders as CSV",
  },
  body: "Adds the export.\n\n- one\n- two",
  pending: [{ kind: "review_notes", text: "The review comments are added to the description." }],
  expect: { tip: "abc" },
  error: null,
};
const COMMENT = {
  node_id: "jira_update",
  tool: "jira.comment",
  action: "comment",
  summary: "Comment on KAN-5",
  target: { kind: "issue", label: "KAN-5", url: "https://acme.atlassian.net/browse/KAN-5" },
  fields: { key: "KAN-5" },
  body: "The fix is in **#42**.\n\n_Posted by agentic-dev run [12345678](https://app.test/runs/x)_",
  pending: [{ kind: "links", text: "Links to the pull request are added once it is open." }],
  expect: {},
  error: null,
};
const MOVE = {
  node_id: "move",
  tool: "jira.transition",
  action: "transition",
  summary: "Move KAN-5 from In Progress to Done",
  target: { kind: "issue", label: "KAN-5", url: "https://acme.atlassian.net/browse/KAN-5" },
  fields: { key: "KAN-5", from_status: "In Progress", to_status: "Done", changed: true },
  body: null,
  pending: [],
  expect: {},
  error: null,
};
const REPO = {
  node_id: "create_repo",
  tool: "github.createRepo",
  action: "create_repo",
  summary: "Create the private repo acme/docs-demo",
  target: { kind: "repo", label: "acme/docs-demo", url: null },
  fields: { full_name: "acme/docs-demo", private: true },
  body: null,
  pending: [],
  expect: {},
  error: null,
};

function plans(...raw: object[]): WritePlan[] {
  return parsePlans(raw);
}

test("each kind of write is a card with its summary, in run order", () => {
  render(<WritePlans plans={plans(API_PLAN, COMMENT, MOVE, REPO)} />);

  const cards = screen.getAllByTestId("write-plan");
  expect(cards.map((c) => c.getAttribute("data-action"))).toEqual([
    "open_pr",
    "comment",
    "transition",
    "create_repo",
  ]);
  expect(screen.getByRole("heading", { name: "What approving does" })).toBeTruthy();
  expect(within(cards[0]!).getByText(/open a pull request into main/)).toBeTruthy();
  expect(within(cards[0]!).getByText("acme/shop").className).toContain("font-mono");
  expect(within(cards[0]!).getByText("Export orders as CSV")).toBeTruthy();
  expect(within(cards[0]!).getByText("· 2 commits")).toBeTruthy();
  expect(within(cards[3]!).getByText("acme/docs-demo").className).toContain("font-mono");
});

test("a transition is shown as from → to in text", () => {
  render(<WritePlans plans={plans(MOVE)} />);

  expect(screen.getByTestId("plan-transition").textContent).toBe("In Progress → Done");
});

test("a move that changes nothing shows no arrow", () => {
  const same = {
    ...MOVE,
    summary: "KAN-5 is already Done: no change",
    fields: { key: "KAN-5", from_status: "Done", to_status: "Done", changed: false },
  };
  render(<WritePlans plans={plans(same)} />);

  expect(screen.queryByTestId("plan-transition")).toBeNull();
  expect(screen.getByText("KAN-5 is already Done: no change")).toBeTruthy();
});

test("what the platform adds after the approval is a quiet line", () => {
  render(<WritePlans plans={plans(COMMENT)} />);

  expect(screen.getByTestId("plan-pending").textContent).toBe(
    "Links to the pull request are added once it is open.",
  );
});

test("a write that would fail has a badge and its error as text", () => {
  const failing = {
    ...MOVE,
    error: { code: "transition_unavailable", message: "KAN-5 is To Do; offered: Start progress" },
  };
  render(<WritePlans plans={plans(failing)} />);

  expect(screen.getByText("Would fail").closest("[data-status]")?.getAttribute("data-status")).toBe(
    "failed",
  );
  expect(screen.getByTestId("plan-error").textContent).toBe(
    "transition_unavailable: KAN-5 is To Do; offered: Start progress",
  );
});

test("an issue is linked only when its address is https", () => {
  const http = { ...COMMENT, target: { ...COMMENT.target, url: "http://acme.test/browse/KAN-5" } };
  const script = { ...COMMENT, target: { ...COMMENT.target, url: "javascript:alert(1)" } };
  const { rerender } = render(<WritePlans plans={plans(COMMENT)} />);
  expect(screen.getByRole("link", { name: /KAN-5/ }).getAttribute("href")).toBe(
    "https://acme.atlassian.net/browse/KAN-5",
  );

  rerender(<WritePlans plans={plans(http)} />);
  expect(screen.queryByRole("link", { name: /KAN-5/ })).toBeNull();
  expect(screen.getByText("KAN-5").className).toContain("font-mono");

  rerender(<WritePlans plans={plans(script)} />);
  expect(screen.queryByRole("link", { name: /KAN-5/ })).toBeNull();
});

test("the body is Markdown with raw HTML and images dropped", () => {
  const hostile = {
    ...COMMENT,
    body: "Hello <script>alert(1)</script><b>bold</b>\n\n![x](https://evil.test/p.png)\n\n**kept**",
  };
  const { container } = render(<WritePlans plans={plans(hostile)} />);

  const body = screen.getByTestId("plan-body");
  expect(within(body).getByText("kept").tagName).toBe("STRONG");
  expect(container.querySelector("script")).toBeNull();
  expect(container.querySelector("img")).toBeNull();
  expect(body.textContent).not.toContain("<script>");
});

test("a long body is capped until Show full", () => {
  const long = { ...COMMENT, body: Array.from({ length: 40 }, (_, i) => `line ${i}`).join("\n\n") };
  render(<WritePlans plans={plans(long)} />);

  const show = screen.getByRole("button", { name: "Show full" });
  expect(show.getAttribute("aria-expanded")).toBe("false");
  expect(screen.getByTestId("plan-body").className).toContain("max-h-64");
  fireEvent.click(show);
  expect(screen.getByRole("button", { name: "Show less" })).toBeTruthy();
  expect(screen.getByTestId("plan-body").className).not.toContain("max-h-64");
});

test("nothing is shown without plans, unless the caller asks for the empty state", () => {
  const { container, rerender } = render(<WritePlans plans={[]} />);
  expect(container.innerHTML).toBe("");

  rerender(<WritePlans plans={[]} empty />);
  expect(screen.getByText("Approving writes nothing outside the run.")).toBeTruthy();
});

test("it has a loading state and an error state with Retry", () => {
  const onRetry = vi.fn();
  const { rerender } = render(<WritePlans plans={[]} loading />);
  expect(screen.getByText("Loading the plans…")).toBeTruthy();

  rerender(<WritePlans plans={[]} error="Could not read them." onRetry={onRetry} />);
  fireEvent.click(screen.getByRole("button", { name: /retry/i }));
  expect(screen.getByText("Could not read them.")).toBeTruthy();
  expect(onRetry).toHaveBeenCalled();
});

test("a plan that is not one is left out", () => {
  expect(parsePlans([{ tool: "jira.comment" }, "x", null, MOVE])).toHaveLength(1);
  expect(parsePlans("nope")).toEqual([]);
});

test("a write that was as planned reads quietly with its gate", () => {
  render(<WriteChecked check={parseWriteCheck({ gate: "approve_pr", outcome: "as_planned" })!} />);

  expect(screen.getByTestId("write-checked").textContent).toBe("As planned at approve_pr");
});

test("a write that was not as planned has a badge and each difference as text", () => {
  const check = parseWriteCheck({
    gate: "approve_pr",
    outcome: "differs",
    differences: [{ field: "base", planned: "main", actual: "develop" }],
  })!;
  render(<WriteChecked check={check} />);

  expect(screen.getByText("Not as planned")).toBeTruthy();
  expect(screen.getByRole("listitem").textContent).toBe("base: planned main, was develop");
});

test("a write refused because its plan went stale says so", () => {
  const check = parseWriteCheck({
    outcome: "stale",
    differences: [{ field: "from_status", planned: "To Do", actual: "In Progress" }],
  })!;
  render(<WriteChecked check={check} />);

  expect(screen.getByText("Plan out of date")).toBeTruthy();
  expect(screen.getByRole("listitem").textContent).toContain("planned To Do, was In Progress");
});
