import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { PageHeader } from "./page-header";

test("renders the title as the page's one h1, with its description and actions", () => {
  render(
    <PageHeader
      title="Runs"
      description="Every run."
      actions={<button type="button">New</button>}
    />,
  );

  expect(screen.getAllByRole("heading", { level: 1 }).map((h) => h.textContent)).toEqual(["Runs"]);
  expect(screen.getByText("Every run.")).toBeDefined();
  expect(screen.getByRole("button", { name: "New" })).toBeDefined();
});

test("leaves out the description and actions when not given", () => {
  const { container } = render(<PageHeader title="Settings" />);

  expect(container.querySelector("p")).toBeNull();
  expect(screen.queryByRole("button")).toBeNull();
});
