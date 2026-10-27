import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import type { RunLimitOverrides, RunLimits, WorkspacePolicy } from "@/api/queries";
import { json, renderWithQueries, stubApi } from "@/testing/api";
import { DEFAULT_WORKSPACE_ID } from "@/workspace";

import { duration, RunLimitsCard } from "./run-limits";

const POLICY_PATH = `/workspaces/${DEFAULT_WORKSPACE_ID}/policy`;

const DEFAULTS: RunLimits = {
  agents_alive: 8,
  agents_spawned: 40,
  max_depth: 2,
  loop_iterations: 5,
  wall_time_s: 7200,
  approval_ttl_s: 259_200,
  budget_usd: null,
};
const UNSET: RunLimitOverrides = {
  agents_alive: null,
  agents_spawned: null,
  max_depth: null,
  loop_iterations: null,
  wall_time_s: null,
  approval_ttl_s: null,
  budget_usd: null,
};

afterEach(() => {
  vi.unstubAllGlobals();
});

function policyOf(overrides: RunLimitOverrides): WorkspacePolicy {
  const effective = { ...DEFAULTS };
  for (const [key, value] of Object.entries(overrides)) {
    if (value != null) effective[key as keyof typeof DEFAULTS] = value;
  }
  return { defaults: DEFAULTS, overrides, effective };
}

/** An API whose stored limits follow PUT. */
function storingApi(start: RunLimitOverrides = UNSET) {
  let stored = start;
  return stubApi({
    [`GET ${POLICY_PATH}`]: () => json(200, policyOf(stored)),
    [`PUT ${POLICY_PATH}`]: async (request) => {
      stored = { ...UNSET, ...((await request.clone().json()) as RunLimitOverrides) };
      return json(200, policyOf(stored));
    },
  });
}

function show() {
  return renderWithQueries(<RunLimitsCard baseUrl="http://api.test" />);
}

function card() {
  return within(screen.getByTestId("limits-card"));
}

function type(label: string, value: string) {
  fireEvent.change(card().getByLabelText(label), { target: { value } });
}

async function putBody(fetch: ReturnType<typeof stubApi>) {
  await waitFor(() => expect(fetch.mock.calls.some(([r]) => r.method === "PUT")).toBe(true));
  return fetch.mock.calls.find(([r]) => r.method === "PUT")?.[0].json();
}

test("with no limits of its own the fields show the platform's as placeholders", async () => {
  storingApi();
  show();

  const alive = await card().findByLabelText("Agents at once");
  expect((alive as HTMLInputElement).value).toBe("");
  expect(alive.getAttribute("placeholder")).toBe("8");
  expect(card().getByText(/Platform limit: 2 h\./)).toBeDefined();
  expect(card().queryByRole("button", { name: "Reset to defaults" })).toBeNull();
});

test("saving sends the lowered limits, with wall time in seconds", async () => {
  const fetch = storingApi();
  show();
  await card().findByLabelText("Agents at once");

  type("Loop iterations", "2");
  type("Wall time hours", "1");
  type("Wall time minutes", "30");
  fireEvent.click(card().getByRole("button", { name: "Save limits" }));

  expect(await putBody(fetch)).toEqual({ ...UNSET, loop_iterations: 2, wall_time_s: 5400 });
  await waitFor(() =>
    expect((card().getByLabelText("Loop iterations") as HTMLInputElement).value).toBe("2"),
  );
  expect(card().getByRole("button", { name: "Reset to defaults" })).toBeDefined();
});

test("limits above the platform's are caught before calling the API", async () => {
  const fetch = storingApi();
  show();
  await card().findByLabelText("Agents at once");

  type("Agents per run", "41");
  type("Wall time hours", "3");
  fireEvent.click(card().getByRole("button", { name: "Save limits" }));

  expect(await card().findByText("From 1 to 40.")).toBeDefined();
  expect(card().getByText("From 1 minute to 2 h.")).toBeDefined();
  expect(card().getByLabelText("Agents per run").getAttribute("aria-invalid")).toBe("true");
  expect(fetch.mock.calls.some(([r]) => r.method === "PUT")).toBe(false);
});

test("stored limits fill the fields, and reset asks first then clears them", async () => {
  const fetch = storingApi({ ...UNSET, agents_alive: 4, wall_time_s: 3600 });
  show();

  const alive = (await card().findByLabelText("Agents at once")) as HTMLInputElement;
  expect(alive.value).toBe("4");
  expect((card().getByLabelText("Wall time hours") as HTMLInputElement).value).toBe("1");
  expect((card().getByLabelText("Wall time minutes") as HTMLInputElement).value).toBe("0");

  fireEvent.click(card().getByRole("button", { name: "Reset to defaults" }));
  fireEvent.click(await screen.findByRole("button", { name: "Reset limits" }));

  expect(await putBody(fetch)).toEqual({});
  await waitFor(() =>
    expect((card().getByLabelText("Agents at once") as HTMLInputElement).value).toBe(""),
  );
});

test("durations read in hours, minutes and seconds", () => {
  expect([7200, 5400, 90, 60, 5].map(duration)).toEqual([
    "2 h",
    "1 h 30 min",
    "1 min 30 s",
    "1 min",
    "5 s",
  ]);
});

test("a budget is saved in dollars, and an empty one is no budget", async () => {
  const fetch = storingApi();
  show();
  const budget = await card().findByLabelText("Budget (USD)");
  expect(budget.getAttribute("placeholder")).toBe("No budget");

  type("Budget (USD)", "2.50");
  fireEvent.click(card().getByRole("button", { name: "Save limits" }));

  expect(await putBody(fetch)).toEqual({ ...UNSET, budget_usd: 2.5 });
});

test("a budget out of range is caught before calling the API", async () => {
  const fetch = storingApi();
  show();
  await card().findByLabelText("Budget (USD)");

  type("Budget (USD)", "0");
  fireEvent.click(card().getByRole("button", { name: "Save limits" }));

  expect(await card().findByText("From $0.01 to $1,000,000.")).toBeDefined();
  type("Budget (USD)", "five");
  fireEvent.click(card().getByRole("button", { name: "Save limits" }));
  expect(await card().findByText("An amount in dollars, like 5 or 2.50.")).toBeDefined();
  expect(fetch.mock.calls.some(([r]) => r.method === "PUT")).toBe(false);
});

test("the approval time to live is entered in hours and saved in seconds", async () => {
  const fetch = storingApi();
  show();
  const ttl = await card().findByLabelText("Approval time to live (hours)");
  expect(ttl.getAttribute("placeholder")).toBe("72");

  type("Approval time to live (hours)", "1.5");
  fireEvent.click(card().getByRole("button", { name: "Save limits" }));

  expect(await putBody(fetch)).toEqual({ ...UNSET, approval_ttl_s: 5400 });
  await waitFor(() =>
    expect((card().getByLabelText("Approval time to live (hours)") as HTMLInputElement).value).toBe(
      "1.5",
    ),
  );
});

test("an approval time to live above the platform's is caught before calling the API", async () => {
  const fetch = storingApi();
  show();
  await card().findByLabelText("Approval time to live (hours)");

  type("Approval time to live (hours)", "100");
  fireEvent.click(card().getByRole("button", { name: "Save limits" }));

  expect(await card().findByText("From 1 minute to 72 h.")).toBeDefined();
  expect(fetch.mock.calls.some(([r]) => r.method === "PUT")).toBe(false);
});
