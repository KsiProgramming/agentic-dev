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

const nav = vi.hoisted(() => ({ search: "", replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => `/runs/00000000-0000-0000-0000-000000000001`,
  useRouter: () => ({ replace: nav.replace }),
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

test("a waiting gate can be approved from its step", async () => {
  const fetch = api(detail({ status: "waiting" }), async () =>
    json({ run_id: RUN_ID, node_id: "gate", decision: "approve", status: "queued" }, 202),
  );
  const source = show();

  act(() => {
    source.emit(runEvent(1, "run_started"));
    source.emit({ ...runEvent(2, "node_started"), node_id: "gate" });
    source.emit({
      ...runEvent(3, "gate_waiting", { title: "Open a PR?", artifact: "<b>x</b>" }),
      node_id: "gate",
    });
  });

  expectStatus("waiting", "Needs approval");
  const step = screen.getAllByTestId("step").find((s) => s.dataset.nodeId === "gate")!;
  const panel = within(step).getByTestId("gate-panel");
  expect(panel.querySelector("b")).toBeNull();
  fireEvent.click(within(panel).getByRole("button", { name: "Approve" }));

  await screen.findByText(/Approved\. The run carries on/);
  const request = fetch.mock.calls
    .map((c) => c[0])
    .find((r): r is Request => typeof r !== "string" && r.url.endsWith("/approvals"))!;
  expect(await request.json()).toEqual({ node_id: "gate", decision: "approve" });

  act(() =>
    source.emit({ ...runEvent(4, "gate_decided", { decision: "approve" }), node_id: "gate" }),
  );
  expect(screen.queryByTestId("gate-panel")).toBeNull();
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
