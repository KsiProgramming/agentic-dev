import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RUN_STATUSES, StatusBadge } from "./status-badge";

describe("StatusBadge", () => {
  it.each(RUN_STATUSES)("shows %s as an icon and a label, not colour alone", (status) => {
    render(<StatusBadge status={status} data-testid="badge" />);

    const badge = screen.getByTestId("badge");
    expect(badge).toHaveProperty("dataset.status", status);
    expect(badge.textContent).toMatch(new RegExp(`^${status}$`, "i"));
    const icon = badge.querySelector("svg");
    expect(icon).not.toBeNull();
    expect(icon?.getAttribute("aria-hidden")).toBe("true");
    expect(badge.className).toContain(`text-status-${status}`);
  });

  it("can say something else while keeping the status", () => {
    render(<StatusBadge status="queued" label="Connecting" data-testid="badge" />);

    const badge = screen.getByTestId("badge");
    expect(badge.textContent).toBe("Connecting");
    expect(badge).toHaveProperty("dataset.status", "queued");
  });
});
