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
