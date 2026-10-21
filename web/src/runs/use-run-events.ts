"use client";

import { useEffect, useState } from "react";

import { apiBaseUrl } from "@/api/client";

import {
  EVENT_TYPES,
  runOutcome,
  type ReceivedRunEvent,
  type RunEvent,
  type StreamStatus,
} from "./types";

export interface RunStream {
  events: ReceivedRunEvent[];
  status: StreamStatus;
}

/** `events` with `event` added in `seq` order. An event already listed is ignored. */
export function insertEvent(
  events: ReceivedRunEvent[],
  event: ReceivedRunEvent,
): ReceivedRunEvent[] {
  if (events.some((e) => e.seq === event.seq)) return events;
  const at = events.findIndex((e) => e.seq > event.seq);
  return at === -1 ? [...events, event] : [...events.slice(0, at), event, ...events.slice(at)];
}

/**
 * A run's events, live: stored ones first, then new ones as they are written. The stream closes
 * after the run's final event. On a dropped connection the browser reconnects by itself and sends
 * `Last-Event-ID`, so the API resumes after the last event received.
 */
export function useRunEvents(runId: string, baseUrl = apiBaseUrl()): RunStream {
  const [stream, setStream] = useState<RunStream>({ events: [], status: "connecting" });

  useEffect(() => {
    const url = `${baseUrl}/runs/${encodeURIComponent(runId)}/events`;
    const source = new EventSource(url);
    const probe = new AbortController();
    let received = false;
    let probing = false;

    const fail = (status: StreamStatus) => {
      source.close();
      setStream((s) => ({ ...s, status }));
    };

    const onEvent = (message: MessageEvent<string>) => {
      const event = JSON.parse(message.data) as RunEvent;
      received = true;
      const outcome = runOutcome(event.type);
      if (outcome) source.close();
      setStream((s) => ({
        events: insertEvent(s.events, { ...event, receivedAt: Date.now() }),
        status: outcome ?? "live",
      }));
    };

    // "message" is in the list, so frames without an `event:` name arrive too.
    for (const type of EVENT_TYPES) source.addEventListener(type, onEvent);

    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) return fail("error");
      // Reconnecting. Before any event, an unknown run looks the same, so ask for the status.
      if (received || probing) return;
      probing = true;
      fetch(url, { signal: probe.signal }).then(
        (response) => {
          probe.abort();
          probing = false;
          if (response.status === 404) fail("not_found");
        },
        () => {
          probing = false;
        },
      );
    };

    return () => {
      source.close();
      probe.abort();
    };
  }, [runId, baseUrl]);

  return stream;
}
