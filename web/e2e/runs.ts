import { expect, type APIRequestContext } from "@playwright/test";

// The API the browser talks to (compose publishes it on the host).
export const apiURL = process.env.E2E_API_URL ?? "http://localhost:8000";

/** Starts a run of `steps` in a sequence through the API and returns its id. */
export async function startRun(request: APIRequestContext, steps: unknown[]): Promise<string> {
  const response = await request.post(`${apiURL}/runs`, {
    data: {
      workflow: {
        spec_version: "0",
        id: "e2e-layout",
        name: "E2E layout",
        root: { type: "sequence", id: "main", steps },
      },
      input: "hello",
    },
  });
  expect(response.status()).toBe(202);
  return ((await response.json()) as { run_id: string }).run_id;
}

export const WRITER = { type: "agent", id: "writer", role: "Writer", instructions: "Say hello." };

export const GATE = {
  type: "gate",
  id: "approve",
  title: "Approve the greeting",
  prompt: "Check it before the run ends.",
};
