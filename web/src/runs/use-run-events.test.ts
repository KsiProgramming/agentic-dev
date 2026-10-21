import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { FakeEventSource, runEvent } from "./testing";
import { useRunEvents } from "./use-run-events";

const RUN_ID = "00000000-0000-0000-0000-000000000001";

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function render() {
  return renderHook(() => useRunEvents(RUN_ID, "http://api.test"));
}

test("opens the run's event stream", () => {
  render();

  expect(FakeEventSource.latest().url).toBe(`http://api.test/runs/${RUN_ID}/events`);
});

test("lists events by seq and drops repeats", () => {
  const { result } = render();
  const source = FakeEventSource.latest();

  act(() => {
    source.emit(runEvent(2, "node_started"));
    source.emit(runEvent(1, "run_started"));
    source.emit(runEvent(2, "node_started"));
  });

  expect(result.current.events.map((e) => e.seq)).toEqual([1, 2]);
  expect(result.current.status).toBe("live");
});

test("records when each event was received", () => {
  vi.spyOn(Date, "now").mockReturnValue(1234);
  const { result } = render();

  act(() => FakeEventSource.latest().emit(runEvent(1, "run_started")));

  expect(result.current.events[0]?.receivedAt).toBe(1234);
});

test.each([
  ["run_completed", "completed"],
  ["run_failed", "failed"],
  ["run_cancelled", "cancelled"],
])("%s ends the run as %s and closes the stream", (type, status) => {
  const { result } = render();
  const source = FakeEventSource.latest();
  expect(result.current.status).toBe("connecting");

  act(() => {
    source.emit(runEvent(1, "run_started"));
    source.emit(runEvent(2, type));
  });

  expect(result.current.status).toBe(status);
  expect(source.readyState).toBe(FakeEventSource.CLOSED);
});

test("an unknown run is not_found", async () => {
  const fetch = vi.fn().mockResolvedValue({ status: 404 });
  vi.stubGlobal("fetch", fetch);
  const { result } = render();
  const source = FakeEventSource.latest();

  // The browser does not retry a 404, so the stream is already closed.
  act(() => source.fail(FakeEventSource.CLOSED));

  await waitFor(() => expect(result.current.status).toBe("not_found"));
  expect(fetch).toHaveBeenCalledWith(source.url, expect.anything());
});

test("an error while connecting keeps retrying when the run exists", async () => {
  const fetch = vi.fn().mockResolvedValue({ status: 200 });
  vi.stubGlobal("fetch", fetch);
  const { result } = render();
  const source = FakeEventSource.latest();

  act(() => source.fail());

  await waitFor(() => expect(fetch).toHaveBeenCalled());
  expect(result.current.status).toBe("connecting");
  act(() => source.emit(runEvent(1, "run_started")));
  expect(result.current.status).toBe("live");
});

test("a reconnect after events keeps the list and does not probe", () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  const { result } = render();
  const source = FakeEventSource.latest();

  act(() => {
    source.emit(runEvent(1, "run_started"));
    source.fail();
    source.emit(runEvent(2, "node_started"));
  });

  expect(fetch).not.toHaveBeenCalled();
  expect(result.current.events.map((e) => e.seq)).toEqual([1, 2]);
  expect(result.current.status).toBe("live");
});

test("a stream the browser gives up on is an error", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ status: 500 }));
  const { result } = render();

  act(() => FakeEventSource.latest().fail(FakeEventSource.CLOSED));

  await waitFor(() => expect(result.current.status).toBe("error"));
});

test("a stream that drops for good after events is an error", () => {
  const { result } = render();
  const source = FakeEventSource.latest();

  act(() => {
    source.emit(runEvent(1, "run_started"));
    source.fail(FakeEventSource.CLOSED);
  });

  expect(result.current.status).toBe("error");
  expect(result.current.events).toHaveLength(1);
});

test("unmounting closes the stream", () => {
  const { unmount } = render();

  unmount();

  expect(FakeEventSource.latest().readyState).toBe(FakeEventSource.CLOSED);
});
