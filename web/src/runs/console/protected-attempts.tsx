import { ShieldIcon } from "lucide-react";
import { useId } from "react";

import { TruncatedPath } from "@/components/display";
import { ErrorState, LoadingState } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import { PROTECTED_RULE_LABEL, type ProtectedAttempt } from "../gates";
import type { ProtectedPaths } from "../timeline";

/** The most attempts listed; the gate's answer keeps at most 50. */
const LISTED = 8;

/**
 * A writer's refused tries to change a protected path (tech-stack → Gate review), listed where a
 * person reviews its work: each with its path (`TruncatedPath`), the rule that refused it and how
 * many times it tried. Nothing renders when there are none: a review with no attempts has no
 * empty box. It has the other two states of a data view: `loading` and an `error` with Retry.
 * Paths are names from the run, shown as text, never as markup.
 */
export function ProtectedAttempts({
  attempts,
  loading = false,
  error,
  onRetry,
  className,
}: {
  attempts: ProtectedAttempt[];
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  className?: string;
}) {
  const headingId = useId();
  if (loading) {
    return <LoadingState rows={2} label="Loading the attempts…" className={className} />;
  }
  if (error) return <ErrorState message={error} onRetry={onRetry} className={className} />;
  if (attempts.length === 0) return null;
  const total = attempts.reduce((sum, a) => sum + a.count, 0);
  const shown = attempts.slice(0, LISTED);
  return (
    <section
      aria-labelledby={headingId}
      data-testid="protected-attempts"
      className={cn("flex min-w-0 flex-col gap-2", className)}
    >
      <h3 id={headingId} className="text-caption font-medium text-muted-foreground">
        Protected files: {total} {total === 1 ? "change was" : "changes were"} refused
      </h3>
      <ul className="flex min-w-0 flex-col divide-y divide-divider rounded-lg border">
        {shown.map((attempt) => (
          <li
            key={`${attempt.nodeId}\u0000${attempt.path}\u0000${attempt.rule}`}
            className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2"
          >
            <span className="min-w-0 flex-1 font-mono text-meta">
              <TruncatedPath path={attempt.path} focusable={false} />
            </span>
            <span className="text-meta text-foreground-secondary">
              <span className="font-mono">{attempt.nodeId}</span>
              {attempt.count > 1 ? ` · ${attempt.count} times` : ""}
            </span>
            <Badge variant="outline">
              <ShieldIcon aria-hidden="true" data-icon="inline-start" />
              {PROTECTED_RULE_LABEL[attempt.rule]}
            </Badge>
          </li>
        ))}
      </ul>
      {attempts.length > shown.length ? (
        <p className="text-meta text-muted-foreground">and {attempts.length - shown.length} more</p>
      ) : null}
    </section>
  );
}

/** What a writer step was told it can read but not change (the Input tab, 13.5): the platform's
 * and the workflow's patterns, then the files frozen at a gate. Patterns and paths are text. */
export function ProtectedPathsList({ paths }: { paths: ProtectedPaths }) {
  const frozenShown = paths.frozen.slice(0, LISTED);
  return (
    <div className="flex min-w-0 flex-col gap-2" data-testid="protected-paths">
      {paths.patterns.length > 0 ? (
        <p className="flex min-w-0 flex-wrap gap-x-2 gap-y-1 font-mono text-meta">
          {paths.patterns.map((pattern) => (
            <span key={pattern}>{pattern}</span>
          ))}
        </p>
      ) : null}
      {paths.frozen.length > 0 ? (
        <div className="flex min-w-0 flex-col gap-1">
          <p className="text-meta text-foreground-secondary">
            Approved
            {paths.gate ? ` at ${paths.gate}` : ""}
            {paths.frozenFrom ? ` from ${paths.frozenFrom}` : ""}, on its branch already:
          </p>
          <ul className="flex flex-col gap-0.5 font-mono text-meta">
            {frozenShown.map((file) => (
              <li key={file}>
                <TruncatedPath path={file} focusable={false} />
              </li>
            ))}
          </ul>
          {paths.frozen.length > frozenShown.length ? (
            <p className="text-meta text-muted-foreground">
              and {paths.frozen.length - frozenShown.length} more
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
