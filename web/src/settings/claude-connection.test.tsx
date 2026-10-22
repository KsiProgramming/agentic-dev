import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import {
  CLAUDE,
  CONNECTIONS_PATH,
  json,
  renderWithQueries,
  requested,
  stubApi,
  type Routes,
} from "@/testing/api";

import { ClaudeConnection } from "./claude-connection";

afterEach(() => {
  vi.unstubAllGlobals();
});

function show() {
  return renderWithQueries(<ClaudeConnection baseUrl="http://api.test" />);
}

function card() {
  return within(screen.getByTestId("claude-card"));
}

function enterKey(key: string) {
  fireEvent.change(screen.getByLabelText("Claude API key"), { target: { value: key } });
}

/** An API whose stored connections follow PUT and DELETE. */
function storingApi(extra: Routes = {}) {
  let stored: (typeof CLAUDE)[] = [];
  return stubApi({
    [`GET ${CONNECTIONS_PATH}`]: () => json(200, stored),
    [`PUT ${CONNECTIONS_PATH}/claude`]: () => {
      stored = [CLAUDE];
      return json(200, CLAUDE);
    },
    [`DELETE ${CONNECTIONS_PATH}/claude`]: () => {
      stored = [];
      return new Response(null, { status: 204 });
    },
    ...extra,
  });
}

test("with no stored key it says so and shows the key form", async () => {
  storingApi();
  show();

  expect(await card().findByText("Not connected")).toBeDefined();
  expect(screen.getByLabelText("Claude API key").getAttribute("type")).toBe("password");
  expect(screen.queryByRole("button", { name: "Remove key" })).toBeNull();
});

test("saving sends the key, then shows only its hint", async () => {
  const fetch = storingApi();
  show();
  await card().findByText("Not connected");

  enterKey("  sk-ant-secret-abcd ");
  fireEvent.click(screen.getByRole("button", { name: "Save key" }));

  await waitFor(() =>
    expect(screen.getByTestId("claude-status").textContent).toContain("ending in …abcd"),
  );
  const put = fetch.mock.calls.find(([r]) => r.method === "PUT")?.[0];
  expect(await put?.json()).toEqual({ api_key: "sk-ant-secret-abcd" });
  expect(card().getByText("Connected")).toBeDefined();
  expect(document.body.textContent).not.toContain("sk-ant-secret-abcd");
});

test("an empty key is caught before calling the API", async () => {
  const fetch = storingApi();
  show();
  await card().findByText("Not connected");

  fireEvent.click(screen.getByRole("button", { name: "Save key" }));

  expect((await screen.findByRole("alert")).textContent).toBe("Paste your Claude API key.");
  expect(screen.getByLabelText("Claude API key").getAttribute("aria-invalid")).toBe("true");
  expect(requested(fetch)).toEqual([`GET ${CONNECTIONS_PATH}`]);
});

test.each([
  [422, "invalid_key", "Anthropic did not accept this key."],
  [502, "verify_unavailable", "Anthropic could not be reached to check the key."],
])("a key refused by its check (%i %s) shows on the field", async (status, code, message) => {
  storingApi({
    [`PUT ${CONNECTIONS_PATH}/claude`]: () => json(status, { detail: { code, message } }),
  });
  show();
  await card().findByText("Not connected");

  enterKey("sk-ant-wrong-key-1234");
  fireEvent.click(screen.getByRole("button", { name: "Save key" }));

  expect((await screen.findByRole("alert")).textContent).toBe(message);
  expect(card().getByText("Not connected")).toBeDefined();
  // The key stays in the field so the user can fix it.
  expect((screen.getByLabelText("Claude API key") as HTMLInputElement).value).toBe(
    "sk-ant-wrong-key-1234",
  );
});

test("an API without a master key explains why the key was not saved", async () => {
  storingApi({
    [`PUT ${CONNECTIONS_PATH}/claude`]: () =>
      json(503, { detail: "secrets are not configured: set MASTER_KEY_FILE on the API" }),
  });
  show();
  await card().findByText("Not connected");

  enterKey("sk-ant-secret-abcd");
  fireEvent.click(screen.getByRole("button", { name: "Save key" }));

  expect((await screen.findByRole("alert")).textContent).toContain("MASTER_KEY_FILE");
});

test("removing asks for confirmation, then deletes the key", async () => {
  const fetch = storingApi({
    [`GET ${CONNECTIONS_PATH}`]: () => json(200, [CLAUDE]),
  });
  show();

  fireEvent.click(await screen.findByRole("button", { name: "Remove key" }));
  const dialog = await screen.findByRole("alertdialog");
  expect(requested(fetch)).toEqual([`GET ${CONNECTIONS_PATH}`]);
  fireEvent.click(within(dialog).getByRole("button", { name: "Remove key" }));

  await waitFor(() => expect(requested(fetch)).toContain(`DELETE ${CONNECTIONS_PATH}/claude`));
});

test("replace opens the key form under the stored key", async () => {
  storingApi({ [`GET ${CONNECTIONS_PATH}`]: () => json(200, [CLAUDE]) });
  show();

  fireEvent.click(await screen.findByRole("button", { name: "Replace key" }));

  expect(screen.getByLabelText("Claude API key")).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByLabelText("Claude API key")).toBeNull();
});

test("an unreachable API shows an error with Retry", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

  show();

  expect((await screen.findByRole("alert")).textContent).toContain("Could not reach the API.");
  expect(screen.getByRole("button", { name: /Retry/ })).toBeDefined();
});
