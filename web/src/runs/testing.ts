import type { RunSummary } from "./summaries";
import type { RunEvent } from "./types";

type Listener = (message: MessageEvent<string>) => void;

/** A scriptable stand-in for the browser's `EventSource`. Install with `vi.stubGlobal`. */
export class FakeEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static instances: FakeEventSource[] = [];

  readyState = FakeEventSource.CONNECTING;
  onerror: (() => void) | null = null;
  private listeners = new Map<string, Listener[]>();

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  static latest(): FakeEventSource {
    const source = FakeEventSource.instances.at(-1);
    if (!source) throw new Error("no EventSource was opened");
    return source;
  }

  addEventListener(type: string, listener: Listener) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  close() {
    this.readyState = FakeEventSource.CLOSED;
  }

  /** Deliver one SSE frame the way the API sends it: `event: <type>`, `data: <RunEvent>`. */
  emit(event: RunEvent) {
    if (this.readyState === FakeEventSource.CLOSED) return;
    this.readyState = FakeEventSource.OPEN;
    const message = new MessageEvent("message", { data: JSON.stringify(event) });
    for (const listener of this.listeners.get(event.type) ?? []) listener(message);
  }

  /** The connection opens (or opens again after a drop). */
  open() {
    this.readyState = FakeEventSource.OPEN;
    for (const listener of this.listeners.get("open") ?? []) listener(new MessageEvent("open"));
  }

  /** Deliver one named SSE frame with `data` as its JSON payload. */
  send(type: string, data: unknown) {
    if (this.readyState === FakeEventSource.CLOSED) return;
    this.readyState = FakeEventSource.OPEN;
    const message = new MessageEvent("message", { data: JSON.stringify(data) });
    for (const listener of this.listeners.get(type) ?? []) listener(message);
  }

  /** A connection error; `readyState` says whether the browser would retry. */
  fail(readyState: number = FakeEventSource.CONNECTING) {
    this.readyState = readyState;
    this.onerror?.();
  }
}

export function runEvent(seq: number, type: string, payload: RunEvent["payload"] = {}): RunEvent {
  return {
    run_id: "00000000-0000-0000-0000-000000000001",
    seq,
    type,
    node_id: type.startsWith("run_") ? null : "summarizer",
    payload,
    created_at: new Date(Date.UTC(2026, 9, 21, 12, 0, seq)).toISOString(),
  };
}

/** A run summary as `GET /runs` lists it; `overrides` change any field. */
export function runSummary(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    id: "00000000-0000-0000-0000-0000000000a1",
    workspace_id: "00000000-0000-0000-0000-000000000001",
    status: "completed",
    workflow: { id: "generate-docs", name: "Generate docs" },
    template_id: "generate-docs",
    repo: { url: "https://github.com/acme/docs", ref: null },
    created_at: "2026-10-22T09:59:58Z",
    started_at: "2026-10-22T10:00:00Z",
    finished_at: "2026-10-22T10:02:05Z",
    duration_ms: 125_000,
    pr_url: null,
    waiting_gate: null,
    rerun_of: null,
    usage: {
      input_tokens: 12_000,
      output_tokens: 3_400,
      cache_read_tokens: 0,
      cache_write_tokens: 0,
      estimated_usd: 0.0582,
      cost_complete: true,
    },
    ...overrides,
  };
}
