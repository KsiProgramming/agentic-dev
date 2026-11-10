import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import type { components } from "@/api/schema";
import type { RunSummary } from "@/runs/summaries";
import { FakeEventSource, runSummary } from "@/runs/testing";

import { InboxView } from "./inbox-view";
import { inboxRuns } from "./waiting";

const nav = vi.hoisted(() => ({ search: "", replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => "/inbox",
  useRouter: () => ({ replace: nav.replace }),
  useSearchParams: () => new URLSearchParams(nav.search),
}));

const LATER = "2999-01-01T00:00:00Z";

function waiting(id: string, created_at: string, title: string): RunSummary {
  return runSummary({
    id,
    status: "waiting",
    created_at,
    finished_at: null,
    duration_ms: null,
    active_ms: 90_000,
    waiting_ms: 3_600_000,
    waiting_gate: { node_id: "gate", title, expires_at: LATER },
  });
}

const older = waiting("r-old", "2026-10-20T08:00:00Z", "Approve the notes");
const newer = waiting("r-new", "2026-10-21T08:00:00Z", "Approve the docs");

type RunGate = components["schemas"]["RunGate"];

function gateOf(runId: string, overrides: Partial<RunGate> = {}): RunGate {
  return {
    node_id: "gate",
    title: runId === older.id ? "Approve the notes" : "Approve the docs",
    prompt: "Check the writer's work.",
    artifact: "# Notes\n\nWhat the repo is for.",
    changes: [],
    changes_error: null,
    run_artifacts: [],
    expires_at: LATER,
    select: null,
    on_reject: "cancel",
    repo: { url: "https://github.com/acme/docs", ref: null },
    base: "main",
    branches: [],
    ...overrides,
  };
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/** Decisions posted, by run id. */
const decisions = new Map<string, unknown>();

/** Answers `GET /runs` with `runs`, `GET /runs/{id}/gate` with `gates[id]` (else 409) and
 * records approvals in `decisions`. */
function api(runs: RunSummary[], gates: Record<string, RunGate> = {}) {
  const fetch = vi.fn<(r: Request) => Promise<Response>>(async (request) => {
    const url = new URL(request.url);
    if (url.pathname === "/runs") return json({ items: runs, next_cursor: null });
    const gate = /^\/runs\/([^/]+)\/gate$/.exec(url.pathname);
    if (gate) {
      const body = gates[gate[1]!];
      return body ? json(body) : json({ detail: "run is queued, not waiting at a gate" }, 409);
    }
    const approval = /^\/runs\/([^/]+)\/approvals$/.exec(url.pathname);
    if (approval && request.method === "POST") {
      const body = (await request.json()) as { node_id: string; decision: string };
      decisions.set(approval[1]!, body);
      return json({ run_id: approval[1], ...body, edited_files: 0 }, 202);
    }
    throw new Error(`unexpected ${request.method} ${request.url}`);
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

/** Makes the viewport 1024 px wide or more (`LG_UP` matches). */
function wide() {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: true,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <InboxView baseUrl="http://api.test" />
    </QueryClientProvider>,
  );
}

function listedTitles(): string[] {
  const list = within(screen.getByRole("navigation", { name: "Waiting gates" }));
  return list.getAllByRole("link").map((link) => link.querySelector("span")?.textContent ?? "");
}

beforeEach(() => {
  nav.search = "";
  nav.replace.mockReset();
  decisions.clear();
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("inboxRuns", () => {
  test("lists the oldest run first and leaves out a gate past its expiry", () => {
    const expired = runSummary({
      id: "r-exp",
      status: "waiting",
      created_at: "2026-10-19T00:00:00Z",
      waiting_gate: { node_id: "gate", title: "Late", expires_at: "2026-10-22T00:00:00Z" },
    });
    const now = Date.parse("2026-10-23T00:00:00Z");
    expect(inboxRuns([newer, expired, older], now).map((r) => r.id)).toEqual(["r-old", "r-new"]);
  });
});

test("the waiting gates are listed oldest first, with their waiting time and expiry", async () => {
  api([newer, older]);
  show();

  await screen.findByRole("navigation", { name: "Waiting gates" });
  expect(listedTitles()).toEqual(["Approve the notes", "Approve the docs"]);
  const first = within(screen.getAllByRole("link", { name: /Approve the notes/ })[0]!);
  expect(first.getByText(/^waiting /)).toBeTruthy();
  expect(first.getByText("acme/docs")).toBeTruthy();
  expect(first.getByText(/^Expires in/)).toBeTruthy();
});

test("from 1024 px the first gate's review is shown beside the list", async () => {
  wide();
  api([newer, older], { [older.id]: gateOf(older.id), [newer.id]: gateOf(newer.id) });
  show();

  const review = await screen.findByTestId("inbox-review");
  expect(within(review).getByRole("heading", { name: "Approve the notes" })).toBeTruthy();
  const current = screen
    .getAllByRole("link")
    .find((link) => link.getAttribute("aria-current") === "true");
  expect(current?.textContent).toContain("Approve the notes");
  // What approving does, and what the run cost and took so far.
  expect(within(review).getByText("Approving lets the run go on")).toBeTruthy();
  expect(within(review).getByText("Active time")).toBeTruthy();
  expect(within(review).getByText("1m 30s")).toBeTruthy();
  expect(within(review).getByText("Cost so far")).toBeTruthy();
  expect(await within(review).findByText("What the repo is for.")).toBeTruthy();
  expect(within(review).getByRole("link", { name: "Open run" }).getAttribute("href")).toBe(
    "/runs/r-old",
  );
});

test("the gate in the URL is the one reviewed; below 1024 px nothing is chosen for the user", async () => {
  api([newer, older], { [older.id]: gateOf(older.id), [newer.id]: gateOf(newer.id) });
  show();
  await screen.findByRole("navigation", { name: "Waiting gates" });
  expect(screen.queryByTestId("inbox-review")).toBeNull();

  nav.search = `run=${newer.id}`;
  show();
  const review = await screen.findByTestId("inbox-review");
  expect(within(review).getByRole("heading", { name: "Approve the docs" })).toBeTruthy();
});

test("a gate with changed files lists them, and what approving lets go on", async () => {
  wide();
  api([older], {
    [older.id]: gateOf(older.id, {
      changes: [
        {
          node_id: "writer",
          path: "NOTES.md",
          old_path: null,
          status: "added",
          editable: true,
          reason: null,
          before: null,
          after: "# Notes\n",
        },
      ],
      branches: [{ node_id: "writer", branch: "agent/r-old/writer" }],
    }),
  });
  show();

  const review = await screen.findByTestId("inbox-review");
  expect(await within(review).findByText("NOTES.md")).toBeTruthy();
  expect(within(review).getByText("agent/r-old/writer")).toBeTruthy();
  expect(within(review).getByText("main")).toBeTruthy();
  expect(within(review).getByRole("button", { name: "Review 1 file" })).toBeTruthy();
});

test("a gate lists the run's artifacts, which open read-only", async () => {
  wide();
  api([older], {
    [older.id]: gateOf(older.id, {
      run_artifacts: [
        {
          name: "findings.json",
          version: 1,
          node_id: "scan",
          media_type: "application/json",
          size: 20,
        },
      ],
    }),
  });
  show();

  const review = await screen.findByTestId("inbox-review");
  const section = await within(review).findByRole("region", { name: "Run artifacts" });
  expect(within(section).getByText("findings.json")).toBeTruthy();
});

test("Approve decides the gate and moves on to the next one", async () => {
  wide();
  api([newer, older], { [older.id]: gateOf(older.id), [newer.id]: gateOf(newer.id) });
  show();

  const review = await screen.findByTestId("inbox-review");
  await within(review).findByText("What the repo is for.");
  fireEvent.click(within(review).getByRole("button", { name: /^Approve/ }));

  await waitFor(() =>
    expect(nav.replace).toHaveBeenCalledWith(`/inbox?run=${newer.id}`, {
      scroll: false,
    }),
  );
  expect(decisions.get(older.id)).toEqual({ node_id: "gate", decision: "approve" });
  // Out of the list at once, before the stream says the run moved on.
  await waitFor(() => expect(listedTitles()).toEqual(["Approve the docs"]));
});

test("A approves the reviewed gate; not while typing in a field", async () => {
  wide();
  api([older], { [older.id]: gateOf(older.id) });
  show();
  const review = await screen.findByTestId("inbox-review");
  await within(review).findByText("What the repo is for.");

  const field = document.createElement("input");
  document.body.append(field);
  fireEvent.keyDown(field, { key: "a" });
  expect(decisions.size).toBe(0);
  field.remove();

  fireEvent.keyDown(window, { key: "a" });
  await waitFor(() =>
    expect(decisions.get(older.id)).toEqual({ node_id: "gate", decision: "approve" }),
  );
});

test("R opens Reject, which asks for a comment", async () => {
  wide();
  api([older], { [older.id]: gateOf(older.id) });
  show();
  const review = await screen.findByTestId("inbox-review");
  await within(review).findByText("What the repo is for.");

  fireEvent.keyDown(window, { key: "r" });
  const dialog = await screen.findByRole("dialog", { name: "Reject “Approve the notes”?" });
  expect(within(dialog).getByLabelText("Comment (optional)")).toBeTruthy();
});

test("a gate no longer waiting says so and links to its run", async () => {
  nav.search = "run=r-gone";
  api([older]);
  show();

  expect(await screen.findByText("This run no longer waits for a decision.")).toBeTruthy();
  expect(screen.getByRole("link", { name: "Open run" }).getAttribute("href")).toBe("/runs/r-gone");
});

test("with nothing waiting, the Inbox says so and links to the runs", async () => {
  api([]);
  show();

  expect(await screen.findByText("Nothing waits for your approval.")).toBeTruthy();
  expect(screen.getByRole("link", { name: "Show all runs" }).getAttribute("href")).toBe("/runs");
});

test("a list that cannot be loaded shows the error and Retry", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => json({ detail: "boom" }, 500)),
  );
  show();

  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
});

test("a gate that cannot be loaded shows the error and Retry in the review", async () => {
  wide();
  const fetch = api([older]);
  fetch.mockImplementation(async (request) => {
    const url = new URL(request.url);
    if (url.pathname === "/runs") return json({ items: [older], next_cursor: null });
    return json({ detail: "boom" }, 500);
  });
  show();

  await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("boom"));
  expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
});
