import { render, screen, within } from "@testing-library/react";
import { expect, test } from "vitest";

import { RunsList } from "./runs-list";
import { runSummary } from "./testing";

test("a waiting run offers Review, which opens its console; others do not", () => {
  render(
    <RunsList
      runs={[
        runSummary({ id: "r-wait", status: "waiting" }),
        runSummary({ id: "r-done", status: "completed" }),
      ]}
      now={Date.now()}
      label="Runs"
    />,
  );

  const table = within(screen.getByRole("table", { name: "Runs" }));
  const reviews = table.getAllByRole("link", { name: /^Review/ });
  expect(reviews).toHaveLength(1);
  expect(reviews[0]!.getAttribute("href")).toBe("/runs/r-wait");
  const cards = within(screen.getByRole("list", { name: "Runs" }));
  expect(cards.getAllByRole("link", { name: /^Review/ })).toHaveLength(1);
});
