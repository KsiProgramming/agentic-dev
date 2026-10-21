import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import Home from "./page";

test("renders the empty app shell", () => {
  render(<Home />);

  expect(screen.getByTestId("app-root")).toBeDefined();
  expect(screen.getByRole("heading", { name: "Agentic Dev Platform" })).toBeDefined();
});
