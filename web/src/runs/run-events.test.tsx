import { act, render, screen, waitFor } from "@testing-library/react";
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

function renderRun() {
  render(<RunEvents runId={RUN_ID} baseUrl="http://api.test" />);
  return FakeEventSource.latest();
}

test("waits for events while connecting", () => {
  renderRun();

  expect(screen.getByTestId("run-status").textContent).toBe("connecting");
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
  expect(screen.getByTestId("run-status").textContent).toBe("live");

  act(() => source.emit(runEvent(3, "run_completed")));

  expect(screen.getByTestId("run-status").textContent).toBe("completed");
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

  act(() => source.fail());

  await waitFor(() => expect(screen.getByText("Run not found.")).toBeDefined());
  expect(screen.getByTestId("run-status").textContent).toBe("not found");
});
