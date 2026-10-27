import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, expect, test, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import { mockReactFlow } from "@/testing/react-flow";

import docsRun from "../fixtures/docs-run.json";
import docsSpec from "../fixtures/docs-run-spec.json";
import { FakeEventSource, runEvent, runSummary } from "../testing";
import type { RunEvent } from "../types";
import type { RunDetail } from "../use-run-detail";
import type { DiffViewProps } from "./diff-view";
import { buildTimeline } from "../timeline";
import { headerFacts, RunConsole } from "./run-console";

const RUN_ID = "00000000-0000-0000-0000-000000000001";

// Monaco needs a real browser: a textarea stands in for the diff's editable side.
vi.mock("./diff-view", () => ({
  default: (props: DiffViewProps) => (
    <textarea
      aria-label={props.labels.modified}
      data-original={props.original}
      value={props.modified}
      readOnly={props.readOnly}
      onChange={(e) => props.onChange?.(e.target.value)}
    />
  ),
}));

const nav = vi.hoisted(() => ({ search: "", replace: vi.fn(), push: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => `/runs/00000000-0000-0000-0000-000000000001`,
  useRouter: () => ({ replace: nav.replace, push: nav.push }),
  useSearchParams: () => new URLSearchParams(nav.search),
}));

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function detail(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    ...runSummary({ id: RUN_ID, status: "running", finished_at: null, duration_ms: null }),
    input: "",
    failure_reason: null,
    spec: docsSpec as RunDetail["spec"],
    ...overrides,
  } as RunDetail;
}

type Handler = (request: Request) => Response | Promise<Response>;

/** Answers `GET /runs/{id}` with `run` (404 for `null`), and other requests with `other`. */
function api(run: RunDetail | null, other?: Handler) {
  const fetch = vi.fn<(r: Request | string) => Promise<Response>>(async (input) => {
    const request = typeof input === "string" ? new Request(input) : input;
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === `/runs/${RUN_ID}`) {
      return run ? json(run) : json({ detail: "no such run" }, 404);
    }
    if (url.pathname === `/runs/${RUN_ID}/events`) return json({ detail: "no such run" }, 404);
    if (other) return other(request);
    throw new Error(`unexpected ${request.method} ${request.url}`);
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <RunConsole runId={RUN_ID} baseUrl="http://api.test" />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return FakeEventSource.latest();
}

function expectStatus(status: string, label: string) {
  const badge = screen.getByTestId("run-status");
  expect(badge.dataset.status).toBe(status);
  expect(badge.textContent).toBe(label);
}

beforeAll(mockReactFlow);

beforeEach(() => {
  nav.search = "";
  nav.replace.mockReset();
  nav.push.mockReset();
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.stubGlobal("scrollTo", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("the header shows the workflow, repo and status from the summary before any event", async () => {
  api(
    detail({
      status: "queued",
      started_at: null,
      repo: { url: "https://github.com/acme/docs", ref: "main" },
    }),
  );
  show();

  await screen.findByRole("heading", { name: "Generate docs" });
  expectStatus("queued", "Queued");
  expect(screen.getByText("acme/docs")).toBeTruthy();
  expect(screen.getByText("main")).toBeTruthy();
  expect(screen.getByText("Waiting for the run to start…")).toBeTruthy();
});

test("Done when (11.2): the header shows active time and the wait apart", () => {
  const t0 = Date.UTC(2026, 9, 27, 9, 0, 0);
  const events = (
    [
      ["run_started", 0],
      ["gate_waiting", 60],
      ["run_resumed", 3660],
      ["run_completed", 3720],
    ] as const
  ).map(([type, seconds], i) => ({
    ...runEvent(i + 1, type),
    created_at: new Date(t0 + seconds * 1000).toISOString(),
    receivedAt: 0,
  }));
  const run = detail({ status: "completed" });

  const facts = headerFacts("completed", events, null, run, buildTimeline(events), null, t0 + 1e8);

  expect(facts).toMatchObject({
    activeMs: 120_000,
    waitingMs: 3_600_000,
    waitingLive: false,
    wallClock: "1h 02m start to end",
  });
});

test("before any event, the header's times are the summary's", () => {
  const run = detail({
    status: "waiting",
    active_ms: 30_000,
    waiting_ms: 0,
    measured_at: "2026-10-22T10:01:00Z",
  });
  const now = Date.parse("2026-10-22T10:03:00Z");

  const facts = headerFacts("live", [], null, run, buildTimeline([]), null, now);

  expect(facts).toMatchObject({ activeMs: 30_000, waitingMs: 120_000, waitingLive: true });
});

test("Done when (11.6): a finished run opens on its last agent's answer", async () => {
  api(detail({ status: "completed" }));
  const source = show();

  act(() => {
    for (const event of docsRun as RunEvent[]) source.emit(event);
  });

  await screen.findByRole("heading", { name: "Generate docs" });
  expectStatus("succeeded", "Succeeded");
  const panel = screen.getByTestId("step-panel");
  expect(panel.dataset.key).toBe("revise#2/reviewer");
  expect(within(panel).getByRole("tab", { name: "Output" }).getAttribute("aria-selected")).toBe(
    "true",
  );
  // The answer alone: earlier messages and tool calls are in Activity.
  expect(within(panel).getAllByTestId("agent-message")).toHaveLength(1);
  expect(screen.queryAllByTestId("event-row")).toHaveLength(0);
  // Every step is one row of the list, map items and iterations nested.
  expect(screen.getAllByTestId("step-row")).toHaveLength(10);
});

test("selecting a step shows its output and puts it in the URL", async () => {
  nav.search = "step=document%5B0%5D%2Fmodule-writer";
  api(detail({ status: "completed" }));
  const source = show();
  act(() => {
    for (const event of docsRun as RunEvent[]) source.emit(event);
  });

  const panel = screen.getByTestId("step-panel");
  expect(panel.dataset.key).toBe("document[0]/module-writer");
  expect(within(panel).getByRole("heading", { level: 2 }).textContent).toBe("packages/api");

  fireEvent.click(screen.getAllByTestId("step-row").find((r) => r.dataset.key === "combine")!);
  expect(nav.replace).toHaveBeenCalledWith(`/runs/${RUN_ID}?step=combine`, { scroll: false });
});

test("the header's tiles show active time, cost against the budget, tokens, steps and output", async () => {
  api(
    detail({
      status: "completed",
      usage: { ...runSummary().usage, budget_usd: 5 },
      pr_url: "https://github.com/acme/api/pull/7",
    }),
  );
  const source = show();
  act(() => {
    for (const event of docsRun as RunEvent[]) source.emit(event);
  });

  const figures = await screen.findByRole("region", { name: "Run figures" });
  const tiles = within(figures)
    .getAllByRole("term")
    .map((t) => t.textContent);
  expect(tiles).toEqual(["Active time", "Cost", "Tokens", "Steps", "Output"]);
  expect((await within(figures).findByTestId("run-budget")).textContent).toBe("of $5.00 budget");
  await waitFor(() => expect(within(figures).getByTestId("run-steps").textContent).toBe("7 of 7"));
  expect(within(figures).getByRole("link", { name: "PR #7" })).toBeTruthy();
});

test("chunks stream into one growing message", async () => {
  api(detail());
  const source = show();

  act(() => {
    source.emit(runEvent(1, "run_started", { workflow_name: "Generate docs" }));
    source.emit(runEvent(2, "node_started"));
    source.emit(runEvent(3, "text_delta", { text: "Hello " }));
  });
  expect(screen.getAllByTestId("agent-message").map((m) => m.textContent)).toEqual(["Hello"]);
  expect(screen.getByTestId("agent-message").dataset.streaming).toBe("true");

  act(() => source.emit(runEvent(4, "text_delta", { text: "world" })));
  expect(screen.getAllByTestId("agent-message").map((m) => m.textContent)).toEqual(["Hello world"]);

  act(() => source.emit(runEvent(5, "message", { text: "Hello world." })));
  expect(screen.getByTestId("agent-message").textContent).toBe("Hello world.");
  expect(screen.getByTestId("agent-message").dataset.streaming).toBeUndefined();
});

test("Raw events folds a streamed message into one row that opens its chunks", async () => {
  nav.search = "tab=raw";
  api(detail());
  const source = show();

  act(() => {
    source.emit(runEvent(1, "run_started"));
    source.emit(runEvent(2, "text_delta", { text: "<img src=x onerror=alert(1)> one " }));
    source.emit(runEvent(3, "text_delta", { text: "two" }));
    source.emit(runEvent(4, "usage", { input_tokens: 1, output_tokens: 2 }));
  });

  // The selected step's events first; the run's own events with "All steps".
  expect(screen.getAllByTestId("event-row").map((r) => r.dataset.type)).toEqual([
    "text_delta",
    "usage",
  ]);
  fireEvent.change(screen.getByLabelText("Step"), { target: { value: "" } });
  const rows = screen.getAllByTestId("event-row");
  expect(rows.map((r) => r.dataset.type)).toEqual(["run_started", "text_delta", "usage"]);
  const folded = rows[1]!;
  expect(folded.dataset.chunks).toBe("2");
  expect(folded.textContent).toContain("<img src=x onerror=alert(1)> one two");
  expect(folded.querySelector("img")).toBeNull();

  fireEvent.click(within(folded).getByRole("button", { name: /text_delta × 2/ }));
  const drawer = await screen.findByTestId("event-drawer");
  expect(within(drawer).getAllByTestId("chunk-row")).toHaveLength(2);
});

test("Done when (11.6): no table cell holds JSON; a payload opens in the drawer", async () => {
  nav.search = "tab=events";
  api(detail());
  const source = show();
  act(() => {
    source.emit({ ...runEvent(1, "node_started", { items: 2 }), node_id: "w" });
    source.emit({
      ...runEvent(2, "tool_call", {
        call_id: "c",
        name: "repo.read_file",
        arguments: { path: "a.ts" },
      }),
      node_id: "w",
    });
    source.emit({
      ...runEvent(3, "tool_result", { call_id: "c", output: '{"text": "x"}' }),
      node_id: "w",
    });
  });

  const cells = screen.getAllByRole("cell").map((c) => c.textContent ?? "");
  for (const cell of cells) expect(cell.trim()).not.toMatch(/^[[{]/);
  expect(cells).toContain("Read a.ts");

  fireEvent.click(screen.getByRole("button", { name: /tool_result/ }));
  const drawer = await screen.findByTestId("event-drawer");
  expect(within(drawer).getByRole("group", { name: "Payload of event 3" }).textContent).toContain(
    "call_id",
  );
});

test("Raw events filters by type and step", async () => {
  nav.search = "tab=raw";
  api(detail());
  const source = show();
  act(() => {
    source.emit(runEvent(1, "run_started"));
    source.emit({ ...runEvent(2, "node_started"), node_id: "a" });
    source.emit({ ...runEvent(3, "node_started"), node_id: "b" });
  });

  // The selected step (b, the one running) is the filter at first.
  expect(screen.getAllByTestId("event-row").map((r) => r.dataset.seq)).toEqual(["3"]);
  fireEvent.change(screen.getByLabelText("Step"), { target: { value: "a" } });
  expect(screen.getAllByTestId("event-row").map((r) => r.dataset.seq)).toEqual(["2"]);
  fireEvent.change(screen.getByLabelText("Step"), { target: { value: "" } });
  fireEvent.change(screen.getByLabelText("Event type"), { target: { value: "run_started" } });
  expect(screen.getAllByTestId("event-row").map((r) => r.dataset.seq)).toEqual(["1"]);
});

test("switching the step's tab keeps it in the URL", async () => {
  api(detail());
  const source = show();
  act(() => {
    source.emit({ ...runEvent(1, "node_started"), node_id: "w" });
  });
  fireEvent.mouseDown(await screen.findByRole("tab", { name: "Events" }), { button: 0 });
  expect(nav.replace).toHaveBeenCalledWith(`/runs/${RUN_ID}?tab=events`, { scroll: false });
});

test("an unknown run says so", async () => {
  api(null);
  show();
  await screen.findByText("Run not found.");
});

function approvals(fetch: ReturnType<typeof api>): Request[] {
  return fetch.mock.calls
    .map((c) => c[0])
    .filter((r): r is Request => typeof r !== "string" && r.url.endsWith("/approvals"));
}

/** A run waiting at gate `gate`, with an artifact holding HTML (data, never markup). */
function waitAtGate(source: FakeEventSource, prompt?: string) {
  act(() => {
    source.emit(runEvent(1, "run_started"));
    source.emit({ ...runEvent(2, "node_started"), node_id: "gate" });
    source.emit({
      ...runEvent(3, "gate_waiting", {
        title: "Open a PR?",
        ...(prompt ? { prompt } : {}),
        artifact: "# Docs written\n\n<b>x</b> under `docs/`.",
      }),
      node_id: "gate",
    });
  });
}

test("the dock says when the gate expires", async () => {
  api(detail({ status: "waiting" }));
  const source = show();
  const expiresAt = new Date(Date.now() + 2 * 86_400_000 + 60_000).toISOString();
  act(() => {
    source.emit(runEvent(1, "run_started"));
    source.emit({
      ...runEvent(2, "gate_waiting", { title: "Open a PR?", expires_at: expiresAt }),
      node_id: "gate",
    });
  });

  const dock = screen.getByRole("region", { name: "Approval needed" });
  expect(within(dock).getByText("Expires in 2 d").getAttribute("dateTime")).toBe(expiresAt);
});

test("Done when (11.3): an expired run shows Expired with the reason", async () => {
  api(detail({ status: "cancelled", expired: true, cancel_reason: "Approval expired" }));
  const source = show();
  act(() => {
    source.emit(runEvent(1, "run_started"));
    source.emit({ ...runEvent(2, "gate_waiting", { title: "Open a PR?" }), node_id: "gate" });
    source.emit(runEvent(3, "run_cancelled", { reason: "Approval expired", expired: true }));
  });

  await waitFor(() => expectStatus("cancelled", "Expired"));
  expect(screen.getByText(/Approval expired: nobody approved or rejected the gate/)).toBeDefined();
  expect(screen.queryByRole("region", { name: "Approval needed" })).toBeNull();
});

test("a run its user cancelled says Cancelled and gives no expiry reason", async () => {
  api(detail({ status: "cancelled", cancel_reason: "cancelled by user" }));
  const source = show();
  act(() => {
    source.emit(runEvent(1, "run_started"));
    source.emit(runEvent(2, "run_cancelled", { reason: "cancelled by user" }));
  });

  await waitFor(() => expectStatus("cancelled", "Cancelled"));
  expect(screen.queryByText(/Approval expired/)).toBeNull();
});

const APPROVED = json(
  { run_id: RUN_ID, node_id: "gate", decision: "approve", status: "queued" },
  202,
);

test("a waiting gate is decided in the dock; its step points there", async () => {
  const fetch = api(detail({ status: "waiting" }), async () => APPROVED.clone());
  const source = show();
  waitAtGate(source);

  expectStatus("waiting", "Needs approval");
  // The gate is selected; the banner and its output point to the dock.
  const step = screen.getByTestId("step-panel");
  expect(step.dataset.key).toBe("gate");
  expect(within(step).getByTestId("waiting-marker").textContent).toContain("Waiting for approval");
  const banner = screen.getByTestId("run-banner");
  expect(banner.dataset.kind).toBe("waiting");
  expect(within(banner).getByRole("link", { name: "Open in Inbox" }).getAttribute("href")).toBe(
    `/inbox?run=${RUN_ID}`,
  );
  const dock = screen.getByRole("region", { name: "Approval needed" });
  expect(within(dock).getByRole("heading", { name: "Open a PR?" })).toBeDefined();
  // No prompt: the summary is the artifact's first line of text.
  expect(within(dock).getByText("Docs written")).toBeDefined();
  expect(dock.querySelector("b")).toBeNull();
  expect(screen.getByTestId("dock-spacer")).toBeDefined();

  fireEvent.click(within(step).getByRole("button", { name: "Go to the decision" }));
  expect(document.activeElement).toBe(dock);

  fireEvent.click(within(dock).getByRole("button", { name: /Approve/ }));
  await within(dock).findByText(/Approved\. The run carries on/);
  expect(await approvals(fetch)[0]!.json()).toEqual({ node_id: "gate", decision: "approve" });

  act(() =>
    source.emit({ ...runEvent(4, "gate_decided", { decision: "approve" }), node_id: "gate" }),
  );
  expect(screen.queryByTestId("approval-dock")).toBeNull();
  expect(screen.queryByTestId("dock-spacer")).toBeNull();
});

test("rejecting asks first, with an optional comment sent with the decision", async () => {
  const fetch = api(detail({ status: "waiting" }), async () =>
    json({ run_id: RUN_ID, node_id: "gate", decision: "reject", status: "queued" }, 202),
  );
  const source = show();
  waitAtGate(source, "Approving pushes the branch.");
  const dock = screen.getByRole("region", { name: "Approval needed" });
  expect(within(dock).getByText("Approving pushes the branch.")).toBeDefined();

  fireEvent.click(within(dock).getByRole("button", { name: /Reject/ }));
  const dialog = await screen.findByRole("dialog", { name: /Reject/ });
  expect(approvals(fetch)).toEqual([]);
  fireEvent.change(within(dialog).getByLabelText("Comment (optional)"), {
    target: { value: "  Wrong folder.  " },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Reject" }));

  await within(dock).findByText(/Rejected\. The run carries on/);
  expect(await approvals(fetch)[0]!.json()).toEqual({
    node_id: "gate",
    decision: "reject",
    comment: "Wrong folder.",
  });
});

test("Review details shows the gate's artifact as Markdown, without its HTML", async () => {
  api(detail({ status: "waiting" }));
  const source = show();
  waitAtGate(source);

  fireEvent.click(screen.getByRole("button", { name: "Review details" }));

  const details = await screen.findByTestId("gate-details");
  expect(within(details).getByRole("heading", { name: "Docs written" })).toBeDefined();
  expect(details.querySelector("b")).toBeNull();
});

test("A approves and R opens Reject, but not while typing or in a dialog", async () => {
  const fetch = api(detail({ status: "waiting" }), async () => APPROVED.clone());
  const source = show();
  waitAtGate(source);

  fireEvent.keyDown(window, { key: "r" });
  const dialog = await screen.findByRole("dialog", { name: /Reject/ });
  const comment = within(dialog).getByLabelText("Comment (optional)");
  fireEvent.keyDown(comment, { key: "a" });
  fireEvent.keyDown(window, { key: "a" });
  expect(approvals(fetch)).toEqual([]);
  fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

  fireEvent.keyDown(window, { key: "a" });
  await waitFor(() => expect(approvals(fetch)).toHaveLength(1));
});

test("a refused decision is shown in the dock and can be tried again", async () => {
  api(detail({ status: "waiting" }), async () =>
    json({ detail: "the run is not waiting at gate" }, 409),
  );
  const source = show();
  waitAtGate(source);

  fireEvent.click(screen.getByRole("button", { name: /Approve/ }));

  expect((await screen.findByRole("alert")).textContent).toBe("the run is not waiting at gate");
  expect(screen.getByRole("button", { name: /Approve/ })).toHaveProperty("disabled", false);
});

const PAGE = {
  node_id: "writer",
  path: "docs/a.md",
  old_path: null,
  status: "added",
  editable: true,
  reason: null,
  before: null,
  after: "# A\n",
};
const LOGO = { ...PAGE, path: "logo.png", editable: false, reason: "binary", after: null };

/** A run waiting at gate `gate` after a writer that added `docs/a.md` and a binary file. */
function waitAtGateWithChanges(source: FakeEventSource) {
  act(() => {
    source.emit(runEvent(1, "run_started"));
    source.emit({ ...runEvent(2, "node_started"), node_id: "gate" });
    source.emit({
      ...runEvent(3, "gate_waiting", {
        title: "Open a PR?",
        prompt: "Approving pushes the branch.",
        artifact: "abc123 on agent/x/writer",
        changes: [PAGE, LOGO],
      }),
      node_id: "gate",
    });
  });
}

async function openReview(): Promise<HTMLElement> {
  fireEvent.click(screen.getByRole("button", { name: "Review details" }));
  return screen.findByTestId("gate-review");
}

test("a gate's changed files open in the review sheet, and edits go with the approval", async () => {
  const fetch = api(detail({ status: "waiting" }), async () =>
    json({ run_id: RUN_ID, node_id: "gate", decision: "approve", status: "queued" }, 202),
  );
  const source = show();
  waitAtGateWithChanges(source);

  const review = await openReview();
  const page = await within(review).findByLabelText("docs/a.md, after (editable)");
  expect(page).toHaveProperty("value", "# A\n");
  expect(within(review).getByText("Added", { selector: "span" })).toBeDefined();
  fireEvent.change(page, { target: { value: "# A, reviewed\n" } });

  expect(within(review).getByText("1 file edited")).toBeDefined();
  expect(within(review).getAllByText("Edited").length).toBeGreaterThan(0);
  const dock = screen.getByTestId("approval-dock");
  // The sheet is modal: the dock behind it is hidden from assistive tech until it closes.
  expect(
    within(dock).getByRole("button", { name: /Approve with 1 edit/, hidden: true }),
  ).toBeDefined();
  // Typing in the editor never approves.
  fireEvent.keyDown(page, { key: "a" });
  expect(approvals(fetch)).toEqual([]);

  // A binary file is listed, read-only, and the edit survives switching files.
  const picker = within(review).getByLabelText(/File 1 of 2/);
  fireEvent.change(picker, { target: { value: "writer\u0000logo.png" } });
  expect(within(review).getByTestId("read-only-reason").textContent).toBe(
    "Binary file: not shown.",
  );
  fireEvent.change(within(review).getByLabelText(/File 2 of 2/), {
    target: { value: "writer\u0000docs/a.md" },
  });
  expect(await within(review).findByLabelText("docs/a.md, after (editable)")).toHaveProperty(
    "value",
    "# A, reviewed\n",
  );

  fireEvent.click(within(review).getByRole("button", { name: /Approve with 1 edit/ }));

  await within(dock).findByText(/Approved\. The run carries on/);
  expect(await approvals(fetch)[0]!.json()).toEqual({
    node_id: "gate",
    decision: "approve",
    edits: [{ node_id: "writer", path: "docs/a.md", content: "# A, reviewed\n" }],
  });
});

test("discarding a file's edits, or typing its text back, leaves nothing to send", async () => {
  api(detail({ status: "waiting" }));
  const source = show();
  waitAtGateWithChanges(source);
  const review = await openReview();
  const page = await within(review).findByLabelText("docs/a.md, after (editable)");

  fireEvent.change(page, { target: { value: "# B\n" } });
  fireEvent.click(within(review).getByRole("button", { name: "Discard edits" }));

  expect(await within(review).findByLabelText("docs/a.md, after (editable)")).toHaveProperty(
    "value",
    "# A\n",
  );
  expect(within(review).getByRole("button", { name: /^Approve$/ })).toBeDefined();
  fireEvent.change(within(review).getByLabelText("docs/a.md, after (editable)"), {
    target: { value: "# A\n" },
  });
  expect(within(review).queryByText("Edited")).toBeNull();
});

test("rejecting with edits says they are dropped", async () => {
  api(detail({ status: "waiting" }));
  const source = show();
  waitAtGateWithChanges(source);
  const review = await openReview();
  fireEvent.change(await within(review).findByLabelText("docs/a.md, after (editable)"), {
    target: { value: "# B\n" },
  });

  fireEvent.click(within(review).getByRole("button", { name: "Reject" }));

  const dialog = await screen.findByRole("dialog", { name: /Reject/ });
  expect(dialog.textContent).toContain("Your edits to 1 file are dropped.");
});

test("an edit the API refuses is shown in the sheet, naming the file", async () => {
  api(detail({ status: "waiting" }), async () =>
    json(
      {
        detail: {
          code: "edit_too_large",
          message: "docs/a.md is 300000 bytes (at most 262144)",
          path: "docs/a.md",
        },
      },
      422,
    ),
  );
  const source = show();
  waitAtGateWithChanges(source);
  const review = await openReview();
  fireEvent.change(await within(review).findByLabelText("docs/a.md, after (editable)"), {
    target: { value: "# B\n" },
  });

  fireEvent.click(within(review).getByRole("button", { name: /Approve with 1 edit/ }));

  expect((await within(review).findByRole("alert")).textContent).toBe(
    "docs/a.md is 300000 bytes (at most 262144)",
  );
  expect(within(review).getByRole("button", { name: /Approve with 1 edit/ })).toHaveProperty(
    "disabled",
    false,
  );
});

test("a gate approved with edits says so, and shows them read-only", async () => {
  api(detail({ status: "running" }));
  const source = show();
  waitAtGateWithChanges(source);
  act(() =>
    source.emit({
      ...runEvent(4, "gate_decided", {
        decision: "approve",
        comment: null,
        edits: [{ node_id: "writer", path: "docs/a.md", content: "# A, reviewed\n" }],
        commits: { writer: "f".repeat(40) },
      }),
      node_id: "gate",
    }),
  );

  const step = screen.getByTestId("step-panel");
  expect(within(step).getByTestId("gate-decision").textContent).toBe(
    "· Approved with edits to 1 file",
  );
  fireEvent.click(within(step).getByRole("button", { name: "View edits" }));

  const review = await screen.findByTestId("gate-review");
  const page = await within(review).findByLabelText("docs/a.md, after");
  expect(page).toHaveProperty("value", "# A, reviewed\n");
  expect(page).toHaveProperty("readOnly", true);
  expect(page.dataset.original).toBe("# A\n");
  expect(within(review).queryByRole("button", { name: /Approve/ })).toBeNull();
});

test("an opened pull request is linked in the header and its step", async () => {
  api(detail());
  const source = show();

  act(() => {
    source.emit(runEvent(1, "run_started"));
    source.emit({
      ...runEvent(2, "pr_opened", { url: "https://github.com/acme/api/pull/3" }),
      node_id: "publish",
    });
    source.emit(runEvent(3, "run_completed"));
  });

  expect(screen.getByTestId("pull-request").getAttribute("href")).toBe(
    "https://github.com/acme/api/pull/3",
  );
  expect(screen.getByRole("link", { name: "Pull request #3" })).toBeTruthy();
});

test("a failed run shows why", async () => {
  api(detail({ status: "failed", failure_reason: "sandbox could not start" }));
  const source = show();
  act(() => {
    source.emit(runEvent(1, "run_started"));
    source.emit(runEvent(2, "run_failed", { error: "sandbox could not start" }));
  });
  const banner = await screen.findByTestId("run-banner");
  expect(banner.textContent).toContain("The run failed");
  expect(banner.textContent).toContain("sandbox could not start");
  expectStatus("failed", "Failed");
});

test("Done when (11.6): a failed run names its failing step and reason above the steps", async () => {
  nav.search = "step=list";
  api(detail({ status: "failed", failure_reason: "writer failed" }));
  const source = show();
  act(() => {
    source.emit(runEvent(1, "run_started"));
    source.emit({ ...runEvent(2, "node_started"), node_id: "list" });
    source.emit({ ...runEvent(3, "node_completed"), node_id: "list" });
    source.emit({ ...runEvent(4, "node_started"), node_id: "writer" });
    source.emit({
      ...runEvent(5, "node_failed", { error: "Rate limited by the provider" }),
      node_id: "writer",
    });
    source.emit(runEvent(6, "run_failed", { error: "writer failed" }));
  });

  const banner = await screen.findByTestId("run-banner");
  expect(banner.dataset.kind).toBe("failed");
  expect(banner.textContent).toContain("Failed at writer");
  expect(banner.textContent).toContain("Rate limited by the provider");
  // The banner comes before the step list in the page.
  const list = screen.getByRole("navigation", { name: "Steps" });
  expect(banner.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

  fireEvent.click(within(banner).getByRole("button", { name: "Go to step" }));
  expect(nav.replace).toHaveBeenCalledWith(`/runs/${RUN_ID}?step=writer`, { scroll: false });
});

test("a lost stream can be retried", async () => {
  api(detail());
  const first = show();
  act(() => {
    first.emit(runEvent(1, "run_started"));
    first.fail(FakeEventSource.CLOSED);
  });

  expectStatus("failed", "Disconnected");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));

  const second = FakeEventSource.latest();
  expect(second).not.toBe(first);
  act(() => second.emit(runEvent(1, "run_started")));
  await waitFor(() => expectStatus("running", "Running"));
});

test("a live run can be cancelled after confirming", async () => {
  const fetch = api(detail(), async () => json({ run_id: RUN_ID, status: "cancelling" }, 202));
  const source = show();
  act(() => source.emit(runEvent(1, "run_started")));

  fireEvent.click(await screen.findByRole("button", { name: "Cancel run" }));
  const dialog = await screen.findByRole("alertdialog", { name: "Cancel this run?" });
  expect(fetch.mock.calls.some(([r]) => typeof r !== "string" && r.url.endsWith("/cancel"))).toBe(
    false,
  );
  fireEvent.click(within(dialog).getByRole("button", { name: "Cancel run" }));

  await screen.findByRole("button", { name: "Cancelling…" });
  const request = fetch.mock.calls
    .map((c) => c[0])
    .find((r): r is Request => typeof r !== "string" && r.url.endsWith("/cancel"))!;
  expect(request.method).toBe("POST");
  expect(request.url).toBe(`http://api.test/runs/${RUN_ID}/cancel`);

  act(() => source.emit(runEvent(2, "run_cancelled", { reason: "cancelled by user" })));
  expectStatus("cancelled", "Cancelled");
  expect(screen.queryByRole("button", { name: /Cancel/ })).toBeNull();
});

test("an ended run offers no Cancel", async () => {
  api(detail({ status: "completed" }));
  const source = show();
  act(() => {
    source.emit(runEvent(1, "run_started"));
    source.emit(runEvent(2, "run_completed"));
  });
  await screen.findByRole("heading", { name: "Generate docs" });
  expect(screen.queryByRole("button", { name: "Cancel run" })).toBeNull();
});

test("an ended run can be rerun from the header, which opens the new run", async () => {
  const NEW_ID = "00000000-0000-0000-0000-0000000000b2";
  const fetch = api(detail({ status: "failed", failure_reason: "boom" }), async (request) =>
    request.url.endsWith(`/runs/${RUN_ID}/rerun`)
      ? json({ run_id: NEW_ID, status: "queued", events_url: "" }, 202)
      : json({ detail: "unexpected" }, 500),
  );
  const source = show();
  act(() => {
    source.emit(runEvent(1, "run_started"));
    source.emit(runEvent(2, "run_failed", { error: "boom" }));
  });

  const rerun = await screen.findByRole("button", { name: "Rerun" });
  expect(screen.queryByRole("button", { name: /Cancel run/ })).toBeNull();
  fireEvent.click(rerun);

  await waitFor(() => expect(nav.push).toHaveBeenCalledWith(`/runs/${NEW_ID}`));
  expect(
    fetch.mock.calls.some(
      ([r]) => typeof r !== "string" && r.method === "POST" && r.url.endsWith("/rerun"),
    ),
  ).toBe(true);
});

test("a live run offers Cancel, not Rerun", async () => {
  api(detail({ status: "running" }));
  const source = show();
  act(() => source.emit(runEvent(1, "run_started")));

  expect(await screen.findByRole("button", { name: /Cancel run/ })).toBeDefined();
  expect(screen.queryByRole("button", { name: "Rerun" })).toBeNull();
});

test("a rerun links back to the run it repeats", async () => {
  const ORIGINAL = "00000000-0000-0000-0000-0000000000c3";
  api(detail({ status: "running", rerun_of: ORIGINAL }));
  show();

  const link = await screen.findByRole("link", { name: `Run ${ORIGINAL.slice(0, 8)}` });
  expect(link.getAttribute("href")).toBe(`/runs/${ORIGINAL}`);
  expect(link.parentElement?.textContent).toBe(`Rerun of ${ORIGINAL.slice(0, 8)}`);
});

test("?tab=graph opens the graph of the run's workflow", async () => {
  nav.search = "tab=graph";
  api(detail({ status: "completed" }));
  const source = show();

  act(() => {
    for (const event of docsRun as RunEvent[]) source.emit(event);
  });

  expect(screen.getByRole("tab", { name: "Graph" }).getAttribute("aria-selected")).toBe("true");
  await waitFor(() => expect(screen.getAllByTestId("graph-node")).toHaveLength(7));
  const reviewer = screen.getAllByTestId("graph-node").find((n) => n.dataset.nodeId === "reviewer");
  expect(reviewer?.dataset.status).toBe("completed");
});

test("switching to the graph puts it in the URL", async () => {
  api(detail());
  show();
  await screen.findByRole("heading", { name: "Generate docs" });

  const graph = screen.getByRole("tab", { name: "Graph" });
  // Radix tabs switch on mouse down.
  fireEvent.mouseDown(graph, { button: 0 });

  expect(nav.replace).toHaveBeenCalledWith(
    "/runs/00000000-0000-0000-0000-000000000001?view=graph",
    {
      scroll: false,
    },
  );
});

test("clicking a graph node selects its step", async () => {
  nav.search = "view=graph";
  api(detail({ status: "completed" }));
  const source = show();
  act(() => {
    for (const event of docsRun as RunEvent[]) source.emit(event);
  });

  await waitFor(() => expect(screen.getAllByTestId("graph-node")).toHaveLength(7));
  fireEvent.click(screen.getAllByTestId("graph-node").find((n) => n.dataset.nodeId === "combine")!);
  expect(nav.replace).toHaveBeenCalledWith(`/runs/${RUN_ID}?view=graph&step=combine`, {
    scroll: false,
  });
});

/** A finished run whose one agent wrote two files and gave a long answer. */
function longAnswer(source: FakeEventSource) {
  const answer = Array.from({ length: 30 }, (_, i) => `Line ${i + 1}`).join("\n");
  act(() => {
    source.emit(runEvent(1, "run_started"));
    source.emit({ ...runEvent(2, "node_started"), node_id: "writer" });
    for (const [seq, path] of [
      [3, "docs/a.md"],
      [5, "docs/b.md"],
    ] as const) {
      source.emit({
        ...runEvent(seq, "tool_call", {
          call_id: path,
          name: "repo.write_file",
          arguments: { path, content: `# ${path}` },
        }),
        node_id: "writer",
      });
      source.emit({
        ...runEvent(seq + 1, "tool_result", { call_id: path, output: "ok" }),
        node_id: "writer",
      });
    }
    source.emit({ ...runEvent(7, "message", { text: answer }), node_id: "writer" });
    source.emit({
      ...runEvent(8, "usage", { input_tokens: 1200, output_tokens: 300, estimated_usd: 0.02 }),
      node_id: "writer",
    });
    source.emit({ ...runEvent(9, "node_completed"), node_id: "writer" });
    source.emit(runEvent(10, "run_completed"));
  });
}

test("a long answer is capped with Show full output; written files open as text", async () => {
  api(detail({ status: "completed" }));
  longAnswer(show());

  const answer = await screen.findByTestId("step-answer");
  expect(answer.dataset.capped).toBe("true");
  fireEvent.click(screen.getByRole("button", { name: "Show full output" }));
  expect(answer.dataset.capped).toBeUndefined();
  expect(screen.getByRole("button", { name: "Show less" })).toBeTruthy();

  const files = screen.getAllByTestId("written-file");
  expect(files.map((f) => f.textContent)).toEqual(["docs/a.mdMarkdown", "docs/b.mdMarkdown"]);
  fireEvent.click(files[1]!);
  const sheet = await screen.findByTestId("written-file-sheet");
  expect(within(sheet).getByText("# docs/b.md").tagName).toBe("PRE");
});

const WRITER_RUN = {
  status: "completed",
  input: "Document the API",
  spec: {
    ...docsSpec,
    root: {
      type: "agent",
      id: "writer",
      role: "Technical writer",
      instructions: "Write the docs.",
      tools: ["repo.write_file"],
    },
  },
} as Partial<RunDetail>;

test("a step's Activity folds its work into one line, opened to show the calls", async () => {
  nav.search = "tab=activity";
  api(detail(WRITER_RUN));
  longAnswer(show());
  const block = await screen.findByTestId("work-block");
  expect(screen.queryByTestId("tool-group")).toBeNull();
  fireEvent.click(within(block).getAllByRole("button")[0]!);
  expect(screen.getAllByTestId("tool-group").length).toBeGreaterThan(0);
});

test("a step's Input shows what the spec and the run gave it", async () => {
  nav.search = "tab=input";
  api(detail(WRITER_RUN));
  longAnswer(show());
  const panel = await screen.findByTestId("step-panel");
  await within(panel).findByText("Technical writer");
  expect(within(panel).getByText("Document the API")).toBeTruthy();
  expect(within(panel).getByText("repo.write_file")).toBeTruthy();
});

test("a step's Usage shows its tokens and cost", async () => {
  nav.search = "tab=usage";
  api(detail(WRITER_RUN));
  longAnswer(show());
  expect((await screen.findByTestId("step-cost")).textContent).toBe("$0.02");
});

test("the ⋯ menu downloads the run's events", async () => {
  api(detail({ status: "completed" }));
  longAnswer(show());
  const createObjectURL = vi.fn(() => "blob:events");
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() }));
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

  fireEvent.pointerDown(screen.getByRole("button", { name: "More actions" }), {
    button: 0,
    ctrlKey: false,
  });
  fireEvent.click(await screen.findByRole("menuitem", { name: "Download events" }));

  expect(createObjectURL).toHaveBeenCalledTimes(1);
  expect((click.mock.contexts[0] as HTMLAnchorElement).download).toBe(
    `run-${RUN_ID.slice(0, 8)}-events.json`,
  );
  click.mockRestore();
});
