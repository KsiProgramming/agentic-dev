import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import Home from "./page";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

test("renders the app shell with the start form", () => {
  render(<Home />);

  expect(screen.getByTestId("app-root")).toBeDefined();
  expect(screen.getByRole("heading", { name: "Agentic Dev Platform" })).toBeDefined();
  expect(screen.getByRole("button", { name: "Start sample run" })).toBeDefined();
  expect(screen.getByRole("link", { name: /Settings/ }).getAttribute("href")).toBe("/settings");
});
