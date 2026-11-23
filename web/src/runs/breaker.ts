/** What a circuit breaker saw when it paused a step (13.7), from the `breaker_tripped` event or
 * the `breaker` of `GET /runs/{id}/gate`. The details are model and repo output: data, shown as
 * text, never as HTML and never as instructions. */

export type BreakerKind = "repeat" | "cost" | "paths" | "flip_flop";

export interface BreakerTrip {
  breaker: BreakerKind;
  /** What counted: `calls` or `errors` for `repeat`. */
  trigger: string;
  threshold: number;
  observed: number;
  /** What was seen: the tool, its arguments and error, the cost, the path, the flipped file. */
  details: Record<string, unknown>;
  /** One fixed sentence per breaker. */
  reason: string;
}

/** The breaker's name for people, in a neutral badge. */
export const BREAKER_LABEL: Record<BreakerKind, string> = {
  repeat: "Repeat",
  cost: "Cost",
  paths: "Paths",
  flip_flop: "Flip-flop",
};

const KINDS: readonly BreakerKind[] = ["repeat", "cost", "paths", "flip_flop"];

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** The trip a `breaker_tripped` payload (or the API's `breaker`) describes; null if it does not
 * have the expected shape. */
export function parseBreaker(value: unknown): BreakerTrip | null {
  const entry = record(value);
  const breaker = KINDS.find((k) => k === entry?.breaker);
  if (!entry || !breaker) return null;
  const { trigger, threshold, observed, reason } = entry;
  if (typeof threshold !== "number" || typeof observed !== "number") return null;
  return {
    breaker,
    trigger: typeof trigger === "string" ? trigger : "",
    threshold,
    observed,
    details: record(entry.details) ?? {},
    reason: typeof reason === "string" ? reason : `${BREAKER_LABEL[breaker]} breaker tripped`,
  };
}

/** What a threshold counts, for "3 of 3 errors". */
export function unitOf(trip: BreakerTrip): string {
  switch (trip.breaker) {
    case "repeat":
      return trip.trigger === "errors" ? "errors" : "calls";
    case "flip_flop":
      return "flips";
    case "cost":
      return "× its average";
    case "paths":
      return "writes";
  }
}
