import { expect, type APIRequestContext } from "@playwright/test";

// The API the browser talks to (compose publishes it on the host).
export const apiURL = process.env.E2E_API_URL ?? "http://localhost:8000";

/** Starts a run of `steps` in a sequence through the API and returns its id. */
export async function startRun(
  request: APIRequestContext,
  steps: unknown[],
  name = "E2E layout",
): Promise<string> {
  const response = await request.post(`${apiURL}/runs`, {
    data: {
      workflow: {
        spec_version: "0",
        id: "e2e-layout",
        name,
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

/** A loop whose `until` is not a bool: it fails after its first round, and so does the run. */
export const FAILING = {
  type: "loop",
  id: "broken",
  body: { type: "agent", id: "draft", role: "Writer", instructions: "Say hello." },
  until: "iteration",
  max_iterations: 2,
};

/** A map over two items, each written by an agent, then combined: containers on the graph. */
export const MAP = {
  type: "map",
  id: "each",
  over: '["alpha", "beta"]',
  max_concurrency: 2,
  body: { type: "agent", id: "worker", role: "Writer", instructions: "Say hello." },
};

export const COMBINE = { type: "reduce", id: "combine", from: "each", strategy: "concat" };
