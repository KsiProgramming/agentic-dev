import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import TemplatesPage from "./page";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

afterEach(() => vi.unstubAllGlobals());

test("renders the docs card and the start form under a page header", async () => {
  // No connections: the docs card asks to connect GitHub.
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json([])));
  render(<TemplatesPage />);

  expect(screen.getByRole("heading", { level: 1, name: "Templates" })).toBeDefined();
  expect(screen.getByRole("heading", { name: "Generate docs" })).toBeDefined();
  expect(screen.getByRole("button", { name: "Start sample run" })).toBeDefined();
  await screen.findByRole("link", { name: /install the GitHub App/ });
});
