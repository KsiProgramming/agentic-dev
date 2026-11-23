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
    changes_left: 0,
    iteration: 1,
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

/** When set, the next approvals are refused with this 422 body. */
let refusal: { code: string; message: string } | null = null;

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
      if (refusal) return json({ detail: refusal }, 422);
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
  refusal = null;
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

  test("leaves out a run that waits for an answer on Jira: nobody decides it (7.9)", () => {
    const waiting = runSummary({
      id: "r-wait",
      status: "waiting",
      created_at: "2026-10-19T00:00:00Z",
      waiting_gate: {
        node_id: "wait_for_answers",
        title: "Waiting for answers",
        expires_at: null,
        wait_for: {
          kind: "jira_comment",
          issue: { key: "KAN-5", url: "https://acme.atlassian.net/browse/KAN-5" },
          after_comment_id: "10001",
        },
      },
    });
    const now = Date.parse("2026-10-23T00:00:00Z");
    expect(inboxRuns([waiting, older], now).map((r) => r.id)).toEqual(["r-old"]);
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
          protected: false,
          rule: null,
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

test("a run a circuit breaker paused is reviewed with what tripped, Resume and Cancel run", async () => {
  wide();
  const reason = "repo.read_file failed 3 times with the same error in one step";
  const paused = runSummary({
    ...older,
    waiting_gate: { node_id: "b", title: null, breaker: "repeat", reason, expires_at: LATER },
  });
  const breaker = {
    breaker: "repeat",
    trigger: "errors",
    threshold: 3,
    observed: 3,
    details: { tool: "repo.read_file", arguments: { path: "gone.md" }, error: "no such file" },
    reason,
  } as const;
  api([paused], {
    [older.id]: gateOf(older.id, { node_id: "b", title: null, artifact: "", breaker }),
  });
  show();

  const review = await screen.findByTestId("inbox-review");
  expect(within(review).getByRole("heading", { level: 2 }).textContent).toContain("Paused:");
  const details = within(review).getByTestId("breaker-details");
  expect(details.textContent).toContain("3 errors, reached 3");
  expect(details.textContent).toContain("no such file");
  expect(within(review).queryByText("Approving lets the run go on")).toBeNull();
  expect(within(review).queryByRole("button", { name: /Approve|Reject/ })).toBeNull();
  expect(within(review).getByRole("button", { name: /Cancel run/ })).toBeTruthy();

  fireEvent.click(within(review).getByRole("button", { name: /Resume/ }));
  await waitFor(() =>
    expect(decisions.get(older.id)).toEqual({ node_id: "b", decision: "approve" }),
  );
});

const REVIEW = {
  from: "review.json",
  version: 1,
  block_at: "high",
  rounds_left: 1,
  comments: [
    {
      fingerprint: "fp-form",
      severity: "medium",
      category: "correctness",
      lenses: ["security"],
      path: "form.py",
      line: 3,
      message: "Name this.",
      node_id: "writer",
      in_diff: true,
      blocking: false,
    },
    {
      fingerprint: "fp-readme",
      severity: "low",
      category: "correctness",
      lenses: ["security"],
      path: "README.md",
      line: 1,
      message: "Mention the validation.",
      node_id: null,
      in_diff: false,
      blocking: false,
    },
  ],
  failed_lenses: [],
  counts: { medium: 1, low: 1 },
  truncated: false,
} satisfies NonNullable<RunGate["review"]>;

test("a gate with a review lists its comments, and approving sends the dismissed ones", async () => {
  wide();
  api([older], { [older.id]: gateOf(older.id, { review: REVIEW }) });
  show();

  const review = await screen.findByTestId("inbox-review");
  expect(await within(review).findByText("Name this.")).toBeTruthy();
  expect(within(review).getByTestId("review-tile")).toBeTruthy();
  const apart = within(review).getByRole("region", { name: "Files the change did not touch" });
  expect(within(apart).getByText("Mention the validation.")).toBeTruthy();

  fireEvent.click(
    within(review).getByRole("button", { name: "Dismiss the comment on README.md:1" }),
  );
  fireEvent.click(within(review).getByRole("button", { name: /^Approve, 1 dismissed/ }));

  await waitFor(() =>
    expect(decisions.get(older.id)).toEqual({
      node_id: "gate",
      decision: "approve",
      dismissed: ["fp-readme"],
    }),
  );
});

test("a gate with a review but no dismissals approves without a dismissed field", async () => {
  wide();
  api([older], { [older.id]: gateOf(older.id, { review: REVIEW }) });
  show();

  const review = await screen.findByTestId("inbox-review");
  await within(review).findByText("Name this.");
  fireEvent.click(within(review).getByRole("button", { name: /^Approve/ }));

  await waitFor(() =>
    expect(decisions.get(older.id)).toEqual({ node_id: "gate", decision: "approve" }),
  );
});

test("a refused dismissal says why in words, not the code", async () => {
  wide();
  refusal = { code: "unknown_dismissal", message: "x is not a comment this gate showed" };
  api([older], { [older.id]: gateOf(older.id, { review: REVIEW }) });
  show();

  const review = await screen.findByTestId("inbox-review");
  await within(review).findByText("Name this.");
  fireEvent.click(
    within(review).getByRole("button", { name: "Dismiss the comment on README.md:1" }),
  );
  fireEvent.click(within(review).getByRole("button", { name: /^Approve/ }));

  const alert = await within(review).findByRole("alert");
  expect(alert.textContent).toContain("Reload the review");
  expect(decisions.size).toBe(0);
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

test("a gate that guards writes shows a plan of each in place of the branches line (13.8)", async () => {
  wide();
  const plans = [
    {
      node_id: "publish",
      tool: "github.openPR",
      action: "open_pr",
      summary: "Push 1 commit to agent/r/writer and open a pull request into main",
      target: { kind: "repo", label: "acme/docs", url: "https://github.com/acme/docs" },
      fields: { head: "agent/r/writer", base: "main", commits: 1 },
      body: "Adds the notes.",
      pending: [],
      expect: {},
      error: null,
    },
    {
      node_id: "move",
      tool: "jira.transition",
      action: "transition",
      summary: "Move KAN-5 from In Progress to Done",
      target: { kind: "issue", label: "KAN-5", url: "https://acme.atlassian.net/browse/KAN-5" },
      fields: { from_status: "In Progress", to_status: "Done", changed: true },
      body: null,
      pending: [],
      expect: {},
      error: {
        code: "transition_unavailable",
        message: "KAN-5 is In Progress; its transitions from there: none",
      },
    },
  ] as unknown as RunGate["plans"];
  api([older], { [older.id]: gateOf(older.id, { plans }) });
  show();

  const review = await screen.findByTestId("inbox-review");

  const cards = await within(review).findAllByTestId("write-plan");
  expect(cards).toHaveLength(2);
  expect(within(review).getByRole("heading", { name: "What approving does" })).toBeTruthy();
  expect(within(review).queryByText("Approving lets the run go on")).toBeNull();
  expect(within(cards[0]!).getByText("Adds the notes.")).toBeTruthy();
  expect(within(cards[1]!).getByTestId("plan-transition").textContent).toBe("In Progress → Done");
  // A plan that would fail is shown, and Approve stays on: the run refuses it before writing.
  expect(within(cards[1]!).getByText("Would fail")).toBeTruthy();
  expect(
    (within(review).getByRole("button", { name: /^Approve/ }) as HTMLButtonElement).disabled,
  ).toBe(false);
});
