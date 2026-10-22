import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";

import docsRun from "../fixtures/docs-run.json";
import { FakeEventSource, runEvent, runSummary } from "../testing";
import type { RunEvent } from "../types";
import type { RunDetail } from "../use-run-detail";
import { RunConsole } from "./run-console";

const RUN_ID = "00000000-0000-0000-0000-000000000001";

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

test("a docs run shows one message block per agent turn, not one row per chunk", async () => {
  api(detail({ status: "completed" }));
  const source = show();

  act(() => {
    for (const event of docsRun as RunEvent[]) source.emit(event);
  });

  await screen.findByRole("heading", { name: "Generate docs" });
  expectStatus("succeeded", "Succeeded");
  const messages = screen.getAllByTestId("agent-message");
  expect(messages).toHaveLength(8);
  expect(messages[0]?.textContent).toBe("I will look at the files of packages/api first.");
  expect(screen.queryAllByTestId("event-row")).toHaveLength(0);
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

test("Raw events folds a streamed message into one row, expandable to its chunks", async () => {
  nav.search = "tab=raw";
  api(detail());
  const source = show();

  act(() => {
    source.emit(runEvent(1, "run_started"));
    source.emit(runEvent(2, "text_delta", { text: "<img src=x onerror=alert(1)> one " }));
    source.emit(runEvent(3, "text_delta", { text: "two" }));
    source.emit(runEvent(4, "usage", { input_tokens: 1, output_tokens: 2 }));
  });

  const rows = screen.getAllByTestId("event-row");
  expect(rows.map((r) => r.dataset.type)).toEqual(["run_started", "text_delta", "usage"]);
  const folded = rows[1]!;
  expect(folded.dataset.chunks).toBe("2");
  expect(folded.textContent).toContain("<img src=x onerror=alert(1)> one two");
  expect(folded.querySelector("img")).toBeNull();

  fireEvent.click(within(folded).getByRole("button", { name: /text_delta × 2/ }));
  expect(screen.getAllByTestId("chunk-row")).toHaveLength(2);
});

test("Raw events filters by type and node", async () => {
  nav.search = "tab=raw";
  api(detail());
  const source = show();
  act(() => {
    source.emit(runEvent(1, "run_started"));
    source.emit({ ...runEvent(2, "node_started"), node_id: "a" });
    source.emit({ ...runEvent(3, "node_started"), node_id: "b" });
  });

  fireEvent.change(screen.getByLabelText("Node"), { target: { value: "b" } });
  expect(screen.getAllByTestId("event-row").map((r) => r.dataset.seq)).toEqual(["3"]);
  fireEvent.change(screen.getByLabelText("Node"), { target: { value: "" } });
  fireEvent.change(screen.getByLabelText("Event type"), { target: { value: "run_started" } });
  expect(screen.getAllByTestId("event-row").map((r) => r.dataset.seq)).toEqual(["1"]);
});

test("switching tabs keeps the tab in the URL", async () => {
  api(detail());
  show();
  fireEvent.mouseDown(await screen.findByRole("tab", { name: "Raw events" }));
  expect(nav.replace).toHaveBeenCalledWith(`/runs/${RUN_ID}?tab=raw`, { scroll: false });
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

const APPROVED = json(
  { run_id: RUN_ID, node_id: "gate", decision: "approve", status: "queued" },
  202,
);

test("a waiting gate is decided in the dock; its step points there", async () => {
  const fetch = api(detail({ status: "waiting" }), async () => APPROVED.clone());
  const source = show();
  waitAtGate(source);

  expectStatus("waiting", "Needs approval");
  const step = screen.getAllByTestId("step").find((s) => s.dataset.nodeId === "gate")!;
  expect(within(step).getByTestId("waiting-marker").textContent).toContain("Waiting for approval");
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
  await screen.findByText("sandbox could not start");
  expectStatus("failed", "Failed");
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

  const link = await screen.findByRole("link", { name: ORIGINAL.slice(0, 8) });
  expect(link.getAttribute("href")).toBe(`/runs/${ORIGINAL}`);
  expect(link.parentElement?.textContent).toBe(`Rerun of ${ORIGINAL.slice(0, 8)}`);
});
