import { fireEvent, render, screen } from "@testing-library/react";
import { InboxIcon } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import { Button } from "@/components/ui/button";

import { EmptyState, ErrorState, LoadingState } from "./states";

describe("EmptyState", () => {
  it("shows its sentence and action", () => {
    render(
      <EmptyState icon={InboxIcon} message="No runs yet." action={<Button>New run</Button>} />,
    );

    expect(screen.getByText("No runs yet.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "New run" })).toBeTruthy();
  });
});

describe("LoadingState", () => {
  it("announces loading and draws skeleton rows", () => {
    const { container } = render(<LoadingState rows={4} label="Loading repos…" />);

    expect(screen.getByRole("status").textContent).toBe("Loading repos…");
    expect(container.querySelectorAll('[data-slot="skeleton"]')).toHaveLength(4);
  });
});

describe("ErrorState", () => {
  it("shows the message and retries on click", () => {
    const onRetry = vi.fn();
    render(<ErrorState message="Could not reach the API." onRetry={onRetry} />);

    expect(screen.getByRole("alert").textContent).toContain("Could not reach the API.");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("has no Retry button when it cannot be retried", () => {
    render(<ErrorState message="Run not found." />);

    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });
});
