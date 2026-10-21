"use client";

import { summarizePayload } from "./summarize";
import type { StreamStatus } from "./types";
import { useRunEvents } from "./use-run-events";

const STATUS_STYLE: Record<StreamStatus, string> = {
  connecting: "bg-gray-100 text-gray-700",
  live: "bg-blue-100 text-blue-800",
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  cancelled: "bg-yellow-100 text-yellow-800",
  not_found: "bg-gray-100 text-gray-700",
  error: "bg-red-100 text-red-800",
};

/** The live event list of one run. Payloads are rendered as text only: they are data. */
export function RunEvents({ runId, baseUrl }: { runId: string; baseUrl?: string }) {
  const { events, status } = useRunEvents(runId, baseUrl);

  return (
    <section className="mt-4">
      <header className="flex items-center gap-3">
        <h1 className="text-xl font-semibold">
          Run <code className="text-base">{runId}</code>
        </h1>
        <span
          data-testid="run-status"
          className={`rounded px-2 py-0.5 text-sm ${STATUS_STYLE[status]}`}
        >
          {status.replace("_", " ")}
        </span>
      </header>

      {status === "not_found" ? (
        <p className="mt-4 text-gray-600">Run not found.</p>
      ) : status === "error" ? (
        <p className="mt-4 text-red-700">Lost the connection to the event stream.</p>
      ) : null}

      {events.length === 0 && (status === "connecting" || status === "live") ? (
        <p className="mt-4 text-gray-500">Waiting for events…</p>
      ) : null}

      {events.length > 0 ? (
        <table className="mt-4 w-full border-collapse text-left text-sm">
          <thead className="border-b text-gray-500">
            <tr>
              <th className="py-1 pr-3 font-medium">#</th>
              <th className="py-1 pr-3 font-medium">Time</th>
              <th className="py-1 pr-3 font-medium">Type</th>
              <th className="py-1 pr-3 font-medium">Node</th>
              <th className="py-1 font-medium">Details</th>
            </tr>
          </thead>
          <tbody>
            {events.map((event) => (
              <tr
                key={event.seq}
                data-testid="event-row"
                data-seq={event.seq}
                data-type={event.type}
                data-created-at={event.created_at}
                data-received-at={event.receivedAt}
                className="border-b border-gray-100 align-top"
              >
                <td className="py-1 pr-3 text-gray-500 tabular-nums">{event.seq}</td>
                <td className="py-1 pr-3 whitespace-nowrap text-gray-500 tabular-nums">
                  {new Date(event.created_at).toLocaleTimeString()}
                </td>
                <td className="py-1 pr-3 font-mono">{event.type}</td>
                <td className="py-1 pr-3 font-mono text-gray-600">{event.node_id ?? ""}</td>
                <td className="py-1 break-all whitespace-pre-wrap">{summarizePayload(event)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}
