import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import Home from "./page";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

afterEach(() => vi.unstubAllGlobals());

test("renders the app shell with the docs card and the start form", async () => {
  // No connections: the docs card asks to connect GitHub.
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json([])));
  render(<Home />);

  expect(screen.getByTestId("app-root")).toBeDefined();
  expect(screen.getByRole("heading", { name: "Agentic Dev Platform" })).toBeDefined();
  expect(screen.getByRole("heading", { name: "Generate docs" })).toBeDefined();
  expect(screen.getByRole("button", { name: "Start sample run" })).toBeDefined();
  expect(screen.getByRole("link", { name: /^Settings/ }).getAttribute("href")).toBe("/settings");
  await screen.findByRole("link", { name: /install the GitHub App/ });
});
