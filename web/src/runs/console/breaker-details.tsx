import { CirclePauseIcon } from "lucide-react";
import { useId, type ReactNode } from "react";

import { Money, TruncatedPath } from "@/components/display";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import { BREAKER_LABEL, unitOf, type BreakerTrip } from "../breaker";
import { describeTool } from "./tool-describe";

function text(value: unknown): string | null {
  return typeof value === "string" && value !== "" ? value : null;
}

function amount(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5 md:flex-row md:gap-3">
      <dt className="shrink-0 text-caption font-medium text-muted-foreground md:w-24">{label}</dt>
      <dd className="min-w-0 break-words text-foreground-secondary">{children}</dd>
    </div>
  );
}

/**
 * Why a circuit breaker paused a step (tech-stack → Circuit breakers): the breaker as a neutral
 * badge, its reason, the threshold and what the step reached, then what it saw: the tool (mono)
 * and its `describeTool` line, the error clamped to two lines, the cost against the node's
 * average, the path with the declared globs, the flipped file and its flips. Everything in it is
 * model or repo output, shown as text and never as markup. It has the three states of a data
 * view: `loading`, an `error` with Retry, and an empty one when there is no trip to show.
 */
export function BreakerDetails({
  trip,
  loading = false,
  error,
  onRetry,
  className,
}: {
  trip: BreakerTrip | null;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  className?: string;
}) {
  const headingId = useId();
  if (loading) return <LoadingState rows={3} label="Loading the pause…" className={className} />;
  if (error) return <ErrorState message={error} onRetry={onRetry} className={className} />;
  if (!trip) {
    return (
      <EmptyState
        icon={CirclePauseIcon}
        message="No circuit breaker paused this step."
        className={className}
      />
    );
  }
  const { details } = trip;
  const tool = text(details.tool);
  const described = tool ? describeTool(tool, details.arguments) : null;
  const errorText = text(details.error);
  const spent = amount(details.spent_usd ?? details.cost_usd);
  const average = amount(details.average_usd);
  const path = text(details.path);
  const globs = strings(details.paths ?? details.declared ?? details.globs);
  const flips = amount(details.flips) ?? (trip.breaker === "flip_flop" ? trip.observed : null);
  return (
    <section
      aria-labelledby={headingId}
      data-testid="breaker-details"
      data-breaker={trip.breaker}
      className={cn("flex min-w-0 flex-col gap-3 rounded-lg border p-3", className)}
    >
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <Badge variant="outline">{BREAKER_LABEL[trip.breaker]} breaker</Badge>
        <h3 id={headingId} className="min-w-0 font-medium break-words">
          {trip.reason}
        </h3>
      </div>
      <dl className="flex min-w-0 flex-col gap-2 text-meta">
        <Row label="Threshold">
          {trip.threshold} {unitOf(trip)}, reached {trip.observed}
        </Row>
        {tool ? (
          <Row label="Tool">
            <span className="font-mono">{tool}</span>
            {described?.target ? (
              <>
                {" "}
                · {described.done} <span className="font-mono">{described.target}</span>
              </>
            ) : null}
          </Row>
        ) : null}
        {errorText ? (
          <Row label="Error">
            <span className="line-clamp-2" title={errorText}>
              {errorText}
            </span>
          </Row>
        ) : null}
        {spent !== null ? (
          <Row label="Cost">
            <Money usd={spent} />
            {average !== null ? (
              <>
                {" "}
                against an average of <Money usd={average} />
              </>
            ) : null}
          </Row>
        ) : null}
        {path ? (
          <Row label="Path">
            <span className="font-mono">
              <TruncatedPath path={path} focusable={false} />
            </span>
          </Row>
        ) : null}
        {globs.length > 0 ? (
          <Row label="Declared">
            <span className="flex flex-wrap gap-x-2 font-mono">
              {globs.map((glob) => (
                <span key={glob}>{glob}</span>
              ))}
            </span>
          </Row>
        ) : null}
        {flips !== null ? (
          <Row label="Flips">
            {flips} {flips === 1 ? "flip" : "flips"}
          </Row>
        ) : null}
      </dl>
    </section>
  );
}
