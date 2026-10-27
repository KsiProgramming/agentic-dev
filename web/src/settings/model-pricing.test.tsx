import { screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { json, renderWithQueries, stubApi } from "@/testing/api";
import { DEFAULT_WORKSPACE_ID } from "@/workspace";

import { ModelPricingCard } from "./model-pricing";

const PRICE = { input: 3, output: 15, cache_write_5m: 3.75, cache_write_1h: 6, cache_read: 0.3 };

afterEach(() => {
  vi.unstubAllGlobals();
});

test("the table has one Cache write column with both windows stacked in its cell", async () => {
  stubApi({
    [`GET /workspaces/${DEFAULT_WORKSPACE_ID}/pricing`]: () =>
      json(200, {
        as_of: "2026-10-01",
        models: [
          { model: "claude-sonnet-5-5", default: PRICE, long_context: null, override: null },
        ],
      }),
  });
  renderWithQueries(<ModelPricingCard baseUrl="http://api.test" />);

  const table = await screen.findByRole("table", { name: /Model prices/ });
  expect(
    within(table)
      .getAllByRole("columnheader")
      .map((h) => h.textContent),
  ).toEqual(["Model", "Input", "Output", "Cache write", "Cache read", "Actions"]);
  const cells = within(table).getAllByRole("cell");
  expect(cells[3].textContent).toBe("5 min$3.751 h$6.00");
  expect(cells[4].textContent).toBe("$0.30");
});
