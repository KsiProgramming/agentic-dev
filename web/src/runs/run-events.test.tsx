import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { RunEvents } from "./run-events";
import { FakeEventSource, runEvent } from "./testing";

const RUN_ID = "00000000-0000-0000-0000-000000000001";

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/** The run status badge: a design-system status and its wording (icon + label). */
function expectStatus(status: string, label: string) {
  const badge = screen.getByTestId("run-status");
  expect(badge.dataset.status).toBe(status);
  expect(badge.textContent).toBe(label);
}

function renderRun() {
  render(<RunEvents runId={RUN_ID} baseUrl="http://api.test" />);
  return FakeEventSource.latest();
}

test("waits for events while connecting", () => {
  renderRun();

  expectStatus("queued", "Connecting");
  expect(screen.getByText("Waiting for events…")).toBeDefined();
});

test("lists events in seq order with their status", () => {
  const source = renderRun();

  act(() => {
    source.emit(runEvent(2, "text_delta", { text: "Hello" }));
    source.emit(runEvent(1, "run_started"));
  });

  const rows = screen.getAllByTestId("event-row");
  expect(rows.map((r) => r.dataset.seq)).toEqual(["1", "2"]);
  expect(rows[1]?.textContent).toContain("text_delta");
  expect(rows[1]?.textContent).toContain("Hello");
  expect(rows[1]?.dataset.receivedAt).toMatch(/^\d+$/);
  expect(rows[1]?.dataset.createdAt).toBe(runEvent(2, "text_delta").created_at);
  expectStatus("running", "Running");

  act(() => source.emit(runEvent(3, "run_completed")));

  expectStatus("succeeded", "Succeeded");
});

test("payloads are shown as text, never as HTML", () => {
  const source = renderRun();

  act(() => source.emit(runEvent(1, "text_delta", { text: "<img src=x onerror=alert(1)>" })));

  const row = screen.getByTestId("event-row");
  expect(row.querySelector("img")).toBeNull();
  expect(row.textContent).toContain("<img src=x onerror=alert(1)>");
});

test("an unknown run says so", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ status: 404 }));
  const source = renderRun();

  act(() => source.fail(FakeEventSource.CLOSED));

  await waitFor(() => expect(screen.getByText("Run not found.")).toBeDefined());
  expectStatus("cancelled", "Not found");
});

test("a waiting gate can be approved", async () => {
  const fetch = vi.fn<(r: Request) => Promise<Response>>(async () =>
    Response.json(
      { run_id: RUN_ID, node_id: "summarizer", decision: "approve", status: "queued" },
      { status: 202 },
    ),
  );
  vi.stubGlobal("fetch", fetch);
  const source = renderRun();

  act(() => {
    source.emit(runEvent(1, "run_started"));
    source.emit(
      runEvent(2, "gate_waiting", { title: "Open a PR?", prompt: null, artifact: "<b>x</b>" }),
    );
  });

  const panel = screen.getByTestId("gate-panel");
  expect(panel.textContent).toContain("Open a PR?");
  expect(panel.textContent).toContain("<b>x</b>");
  expect(panel.querySelector("b")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Approve" }));

  await screen.findByText(/Approved/);
  const request = fetch.mock.calls[0]?.[0] as Request;
  expect(request.url).toBe(`http://api.test/runs/${RUN_ID}/approvals`);
  expect(await request.json()).toEqual({ node_id: "summarizer", decision: "approve" });

  act(() => source.emit(runEvent(3, "gate_decided", { decision: "approve" })));
  expect(screen.queryByTestId("gate-panel")).toBeNull();
});

test("a refused decision shows an error", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ detail: "already decided" }, { status: 409 })),
  );
  const source = renderRun();
  act(() => source.emit(runEvent(1, "gate_waiting", { title: "Go?" })));

  fireEvent.click(screen.getByRole("button", { name: "Reject" }));

  expect((await screen.findByRole("alert")).textContent).toContain("HTTP 409");
});

test("an opened pull request is linked", () => {
  const source = renderRun();

  act(() => {
    source.emit(runEvent(1, "pr_opened", { url: "https://github.com/acme/api/pull/3" }));
    source.emit(runEvent(2, "run_completed"));
  });

  const link = screen.getByRole("link", { name: "https://github.com/acme/api/pull/3" });
  expect(link.getAttribute("href")).toBe("https://github.com/acme/api/pull/3");
});

test("a run waiting at a gate says it needs approval", () => {
  const source = renderRun();

  act(() => source.emit(runEvent(1, "gate_waiting", { title: "Go?" })));

  expectStatus("waiting", "Needs approval");
});

test("a lost stream can be retried", () => {
  const first = renderRun();
  act(() => {
    first.emit(runEvent(1, "run_started"));
    first.fail(FakeEventSource.CLOSED);
  });

  expectStatus("failed", "Disconnected");
  expect(screen.getByRole("alert").textContent).toBe("Lost the connection to the event stream.");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));

  const second = FakeEventSource.latest();
  expect(second).not.toBe(first);
  expectStatus("queued", "Connecting");
  act(() => second.emit(runEvent(1, "run_started")));
  expectStatus("running", "Running");
});
