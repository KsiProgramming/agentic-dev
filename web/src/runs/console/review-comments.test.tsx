import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { parseReview, type Review } from "../review";
import { ReviewComments } from "./review-comments";

function comment(over: Record<string, unknown> = {}) {
  return {
    fingerprint: "fp-1",
    severity: "medium",
    category: "correctness",
    lenses: ["security"],
    path: "form.py",
    line: 3,
    end_line: null,
    message: "Name this.",
    node_id: "implement",
    in_diff: true,
    blocking: false,
    ...over,
  };
}

function review(comments: unknown[] = [comment()], over: Record<string, unknown> = {}): Review {
  const parsed = parseReview({
    from: "review.json",
    version: 2,
    block_at: "high",
    rounds_left: 1,
    comments,
    failed_lenses: [],
    counts: { medium: 1 },
    truncated: false,
    ...over,
  });
  if (!parsed) throw new Error("not a review");
  return parsed;
}

const MIXED = review([
  comment(),
  comment({
    fingerprint: "fp-2",
    severity: "high",
    line: 9,
    message: "Escape it.",
    blocking: true,
  }),
  comment({
    fingerprint: "fp-3",
    severity: "low",
    path: "README.md",
    line: 1,
    message: "Mention the validation.",
    node_id: null,
    in_diff: false,
    lenses: ["security", "performance"],
  }),
]);

describe("ReviewComments", () => {
  it("groups comments by file and lists the files the change did not touch apart", () => {
    render(<ReviewComments review={MIXED} />);

    const file = screen.getByRole("group", { name: "form.py" });
    expect(within(file).getAllByTestId("review-comment")).toHaveLength(2);
    const apart = screen.getByRole("region", { name: "Files the change did not touch" });
    expect(within(apart).getByText("Mention the validation.")).toBeTruthy();
    expect(within(file).queryByText("Mention the validation.")).toBeNull();
  });

  it("shows severity, where, lenses in mono, the message, and Blocking on the blocking one", () => {
    render(<ReviewComments review={MIXED} />);

    const rows = screen.getAllByTestId("review-comment");
    const [first, second] = rows;
    expect(first?.querySelector("[data-severity='medium']")).toBeTruthy();
    expect(within(first!).queryByText("Blocking")).toBeNull();
    expect(within(second!).getByText("Blocking")).toBeTruthy();
    expect(within(second!).getByText("form.py:9")).toBeTruthy();
    expect(within(first!).getByText("security").className).toContain("font-mono");
    expect(within(rows[2]!).getByText("security and performance")).toBeTruthy();
  });

  it("renders a message as text, never as markup", () => {
    const message = "<img src=x onerror=alert(1)> and <b>bold</b>";
    const { container } = render(<ReviewComments review={review([comment({ message })])} />);

    expect(screen.getByText(message)).toBeTruthy();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
  });

  it("toggles Dismiss with aria-pressed on a waiting gate", () => {
    const toggle = vi.fn();
    const { rerender } = render(
      <ReviewComments review={MIXED} dismissed={new Set()} onToggleDismiss={toggle} />,
    );

    const button = screen.getByRole("button", { name: "Dismiss the comment on form.py:3" });
    expect(button.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(button);
    expect(toggle).toHaveBeenCalledWith("fp-1");

    rerender(
      <ReviewComments review={MIXED} dismissed={new Set(["fp-1"])} onToggleDismiss={toggle} />,
    );
    expect(
      screen
        .getByRole("button", { name: "Dismiss the comment on form.py:3" })
        .getAttribute("aria-pressed"),
    ).toBe("true");
  });

  it("has no Dismiss toggle on a decided gate, and says what was dismissed", () => {
    render(<ReviewComments review={MIXED} dismissed={new Set(["fp-3"])} />);

    expect(screen.queryByRole("button", { name: /Dismiss/ })).toBeNull();
    expect(screen.getByText("Dismissed")).toBeTruthy();
  });

  it("selects a comment's file and line from the list, but not a file the change did not touch", () => {
    const select = vi.fn();
    render(<ReviewComments review={MIXED} onSelect={select} />);

    fireEvent.click(screen.getByRole("button", { name: "Show form.py:3 in the diff" }));
    expect(select).toHaveBeenCalledWith(expect.objectContaining({ fingerprint: "fp-1", line: 3 }));
    expect(screen.queryByRole("button", { name: /README\.md/ })).toBeNull();
  });

  it("names a lens that could not run", () => {
    render(<ReviewComments review={review([comment()], { failed_lenses: ["performance"] })} />);

    expect(screen.getByText("The performance lens could not run.")).toBeTruthy();
  });

  it("has the three states", () => {
    const retry = vi.fn();
    const { rerender } = render(<ReviewComments review={null} loading />);
    expect(screen.getByText("Loading the review…")).toBeTruthy();

    rerender(<ReviewComments review={null} error="Could not load the gate." onRetry={retry} />);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalled();

    rerender(<ReviewComments review={review([], { counts: {} })} />);
    expect(screen.getByText("The reviewers had nothing to say about this change.")).toBeTruthy();
  });
});
