import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { json, renderWithQueries, stubApi } from "@/testing/api";
import { DEFAULT_WORKSPACE_ID } from "@/workspace";

import { ProviderSettingsCard } from "./provider-settings";

const PATH = `/workspaces/${DEFAULT_WORKSPACE_ID}/provider-settings`;

const SAVED = {
  default_provider: "claude",
  copilot_model: null,
  copilot_credit_usd: 0.01,
  default_copilot_credit_usd: 0.01,
};

afterEach(() => {
  vi.unstubAllGlobals();
});

function show(routes: Parameters<typeof stubApi>[0] = {}) {
  const fetch = stubApi({ [`GET ${PATH}`]: () => json(200, SAVED), ...routes });
  renderWithQueries(<ProviderSettingsCard baseUrl="http://api.test" />);
  return fetch;
}

async function body(fetch: ReturnType<typeof stubApi>) {
  const put = fetch.mock.calls.find(([r]) => r.method === "PUT")?.[0];
  return put?.json();
}

test("it shows the saved settings, the credit at GitHub's price, and no save bar", async () => {
  show();

  const claude = await screen.findByRole("radio", { name: "Claude" });
  expect(claude).toHaveProperty("checked", true);
  expect(screen.getByRole("radio", { name: "GitHub Copilot" })).toHaveProperty("checked", false);
  expect((screen.getByLabelText(/^Copilot model/) as HTMLInputElement).value).toBe("");
  expect(screen.getByLabelText(/^Copilot AI credit/)).toHaveProperty("value", "0.01");
  expect(screen.getByText("$0.01").textContent).toBe("$0.01");
  expect(screen.queryByTestId("provider-save-bar")).toBeNull();
});

test("a change shows the sticky bar, and Discard puts the saved values back", async () => {
  show();
  fireEvent.click(await screen.findByRole("radio", { name: "GitHub Copilot" }));
  fireEvent.change(screen.getByLabelText(/^Copilot model/), { target: { value: "gpt-5" } });

  expect(screen.getByTestId("provider-save-bar").textContent).toContain("Unsaved changes");
  fireEvent.click(screen.getByRole("button", { name: "Discard" }));

  expect(screen.getByRole("radio", { name: "Claude" })).toHaveProperty("checked", true);
  expect((screen.getByLabelText(/^Copilot model/) as HTMLInputElement).value).toBe("");
  expect(screen.queryByTestId("provider-save-bar")).toBeNull();
});

test("saving sends the provider, the model and a changed credit price", async () => {
  const fetch = show({
    [`PUT ${PATH}`]: () =>
      json(200, {
        ...SAVED,
        default_provider: "copilot",
        copilot_model: "gpt-5",
        copilot_credit_usd: 0.02,
      }),
  });
  fireEvent.click(await screen.findByRole("radio", { name: "GitHub Copilot" }));
  fireEvent.change(screen.getByLabelText(/^Copilot model/), { target: { value: " gpt-5 " } });
  fireEvent.change(screen.getByLabelText(/^Copilot AI credit/), { target: { value: "0.02" } });
  fireEvent.click(screen.getByRole("button", { name: "Save settings" }));

  await waitFor(() => expect(screen.queryByTestId("provider-save-bar")).toBeNull());
  expect(await body(fetch)).toEqual({
    default_provider: "copilot",
    copilot_model: "gpt-5",
    copilot_credit_usd: 0.02,
  });
  expect(screen.getByRole("radio", { name: "GitHub Copilot" })).toHaveProperty("checked", true);
});

test("the credit price goes back to GitHub's with its button, and is sent as unset", async () => {
  const fetch = show({
    [`GET ${PATH}`]: () => json(200, { ...SAVED, copilot_credit_usd: 0.02 }),
    [`PUT ${PATH}`]: () => json(200, SAVED),
  });
  const credit = await screen.findByLabelText(/^Copilot AI credit/);
  expect(credit).toHaveProperty("value", "0.02");

  fireEvent.click(screen.getByRole("button", { name: /Reset to GitHub/ }));
  expect(credit).toHaveProperty("value", "0.01");
  expect(screen.getByRole("button", { name: /Reset to GitHub/ })).toHaveProperty("disabled", true);
  fireEvent.click(screen.getByRole("button", { name: "Save settings" }));

  await waitFor(() => expect(screen.queryByTestId("provider-save-bar")).toBeNull());
  expect(await body(fetch)).toEqual({
    default_provider: "claude",
    copilot_model: null,
    copilot_credit_usd: null,
  });
});

test("a bad price or model is shown on its field and nothing is sent", async () => {
  const fetch = show();
  fireEvent.change(await screen.findByLabelText(/^Copilot AI credit/), {
    target: { value: "free" },
  });
  fireEvent.change(screen.getByLabelText(/^Copilot model/), { target: { value: "not a model" } });
  fireEvent.click(screen.getByRole("button", { name: "Save settings" }));

  expect(await screen.findByText(/A price above 0/)).toBeDefined();
  expect(screen.getByText(/no spaces/)).toBeDefined();
  expect(screen.getByLabelText(/^Copilot AI credit/).getAttribute("aria-invalid")).toBe("true");
  expect(fetch.mock.calls.some(([r]) => r.method === "PUT")).toBe(false);
});

test("a refusal from the server stays on the form", async () => {
  show({ [`PUT ${PATH}`]: () => json(500, { detail: "boom" }) });
  fireEvent.click(await screen.findByRole("radio", { name: "GitHub Copilot" }));
  fireEvent.click(screen.getByRole("button", { name: "Save settings" }));

  expect(await screen.findByRole("alert")).toBeDefined();
  expect(screen.getByTestId("provider-save-bar")).toBeDefined();
});

test("it is skeleton while loading, and an error with Retry", async () => {
  let fail = true;
  show({ [`GET ${PATH}`]: () => (fail ? json(500, { detail: "down" }) : json(200, SAVED)) });

  const retry = await screen.findByRole("button", { name: "Retry" });
  fail = false;
  fireEvent.click(retry);

  expect(await screen.findByRole("radio", { name: "Claude" })).toBeDefined();
});
