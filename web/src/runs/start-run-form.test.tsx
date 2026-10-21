import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { sampleSpec } from "./sample-spec";
import { StartRunForm } from "./start-run-form";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const RUN_ID = "00000000-0000-0000-0000-000000000001";

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

beforeEach(() => {
  push.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function submit(input: string) {
  render(<StartRunForm baseUrl="http://api.test" />);
  fireEvent.change(screen.getByLabelText("Input"), { target: { value: input } });
  fireEvent.click(screen.getByRole("button", { name: "Start sample run" }));
}

test("posts the sample spec with the input and opens the run", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue(
      json(202, { run_id: RUN_ID, status: "queued", events_url: "http://api.test/x" }),
    );
  vi.stubGlobal("fetch", fetch);

  submit("hello");

  await waitFor(() => expect(push).toHaveBeenCalledWith(`/runs/${RUN_ID}`));
  const request = fetch.mock.calls[0]?.[0] as Request;
  expect(request.url).toBe("http://api.test/runs");
  expect(request.method).toBe("POST");
  expect(await request.json()).toEqual({ workflow: sampleSpec, input: "hello" });
});

test("a refused run shows an error and can be retried", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(422, { detail: [] })));

  submit("hello");

  expect((await screen.findByRole("alert")).textContent).toContain("HTTP 422");
  expect(push).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Start sample run" })).toHaveProperty(
    "disabled",
    false,
  );
});

test("an unreachable API shows an error", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

  submit("hello");

  expect((await screen.findByRole("alert")).textContent).toBe("Could not reach the API.");
});
