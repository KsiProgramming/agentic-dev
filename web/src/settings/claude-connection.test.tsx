import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { ClaudeConnection, DEFAULT_WORKSPACE_ID } from "./claude-connection";

const CONNECTIONS = `http://api.test/workspaces/${DEFAULT_WORKSPACE_ID}/connections`;
const STORED = {
  id: "11111111-1111-1111-1111-111111111111",
  provider: "claude",
  key_hint: "abcd",
  created_at: "2026-10-21T10:00:00Z",
  updated_at: "2026-10-21T10:00:00Z",
};

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/** Answers each fetch with the next response, recording the requests. */
function api(...responses: Response[]) {
  const fetch = vi.fn<(r: Request) => Promise<Response>>();
  for (const r of responses) fetch.mockResolvedValueOnce(r);
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function enterKey(key: string) {
  fireEvent.change(screen.getByLabelText("Claude API key"), { target: { value: key } });
}

test("with no stored key it says so and offers to save one", async () => {
  api(json(200, []));

  render(<ClaudeConnection baseUrl="http://api.test" />);

  expect((await screen.findByTestId("claude-status")).textContent).toContain(
    "No Claude key stored",
  );
  expect(screen.getByRole("button", { name: "Save key" })).toHaveProperty("disabled", true);
  expect(screen.queryByRole("button", { name: "Remove key" })).toBeNull();
});

test("saving sends the key, clears the field and shows only its hint", async () => {
  const fetch = api(json(200, []), json(200, STORED));
  render(<ClaudeConnection baseUrl="http://api.test" />);
  await screen.findByTestId("claude-status");

  enterKey("sk-ant-secret-abcd");
  fireEvent.click(screen.getByRole("button", { name: "Save key" }));

  await waitFor(() =>
    expect(screen.getByTestId("claude-status").textContent).toContain("ending in …abcd"),
  );
  const put = fetch.mock.calls[1]?.[0] as Request;
  expect(put.url).toBe(`${CONNECTIONS}/claude`);
  expect(put.method).toBe("PUT");
  expect(await put.json()).toEqual({ api_key: "sk-ant-secret-abcd" });
  expect((screen.getByLabelText("Claude API key") as HTMLInputElement).value).toBe("");
  expect(screen.getByLabelText("Claude API key").getAttribute("type")).toBe("password");
  expect(document.body.textContent).not.toContain("sk-ant-secret-abcd");
  expect(screen.getByRole("button", { name: "Replace key" })).toBeDefined();
});

test("removing asks first, then deletes the key", async () => {
  const fetch = api(json(200, [STORED]), new Response(null, { status: 204 }));
  render(<ClaudeConnection baseUrl="http://api.test" />);

  fireEvent.click(await screen.findByRole("button", { name: "Remove key" }));
  expect(fetch).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Confirm remove" }));

  await waitFor(() =>
    expect(screen.getByTestId("claude-status").textContent).toContain("No Claude key stored"),
  );
  const del = fetch.mock.calls[1]?.[0] as Request;
  expect(del.method).toBe("DELETE");
  expect(del.url).toBe(`${CONNECTIONS}/claude`);
});

test("an API without a master key explains why the key was not saved", async () => {
  api(
    json(200, []),
    json(503, {
      detail: "secrets are not configured: set MASTER_KEY_FILE on the API to store keys",
    }),
  );
  render(<ClaudeConnection baseUrl="http://api.test" />);
  await screen.findByTestId("claude-status");

  enterKey("sk-ant-secret-abcd");
  fireEvent.click(screen.getByRole("button", { name: "Save key" }));

  expect((await screen.findByRole("alert")).textContent).toContain("MASTER_KEY_FILE");
  // The key stays in the field so the user can retry once the API is fixed.
  expect((screen.getByLabelText("Claude API key") as HTMLInputElement).value).toBe(
    "sk-ant-secret-abcd",
  );
});

test("an invalid key is reported without echoing it", async () => {
  api(json(200, []), json(422, { detail: [] }));
  render(<ClaudeConnection baseUrl="http://api.test" />);
  await screen.findByTestId("claude-status");

  enterKey("short");
  fireEvent.click(screen.getByRole("button", { name: "Save key" }));

  expect((await screen.findByRole("alert")).textContent).toBe(
    "That does not look like an API key.",
  );
});

test("an unreachable API shows an error", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

  render(<ClaudeConnection baseUrl="http://api.test" />);

  expect((await screen.findByRole("alert")).textContent).toBe("Could not reach the API.");
});
