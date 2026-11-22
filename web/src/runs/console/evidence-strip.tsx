import { FlaskConicalIcon } from "lucide-react";
import { useId } from "react";

import { Duration, StatStrip, StatTile, TruncatedPath } from "@/components/display";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { StatusBadge } from "@/components/status-badge";
import { cn } from "@/lib/utils";

import {
  CHECK_BADGE,
  CHECK_LABEL,
  failingRequired,
  type Evidence,
  type EvidenceCheck,
} from "../evidence";

/** The most failing tests or findings listed under the strip: the pack keeps 20, and the review
 * shows the first few, as the changed files do. */
const LISTED = 8;

/**
 * What the platform's checks found about the writer's work (tech-stack → Gate review): one tile
 * per check, the outcome as a `StatusBadge`, then the failing tests and new findings under it
 * (names in mono, files as `TruncatedPath`). Test names, files and messages are repo output:
 * text, never markup. It has the three states of a data view: `loading` (skeleton), an `error`
 * with Retry, and an empty pack ("No checks ran").
 */
export function EvidenceStrip({
  evidence,
  loading = false,
  error,
  onRetry,
  className,
}: {
  evidence: Evidence | null;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  className?: string;
}) {
  const headingId = useId();
  if (loading) return <LoadingState rows={2} label="Loading the checks…" className={className} />;
  if (error) return <ErrorState message={error} onRetry={onRetry} className={className} />;
  if (!evidence) return null;
  if (evidence.checks.length === 0) {
    return (
      <EmptyState
        icon={FlaskConicalIcon}
        message="No checks ran for this change."
        className={className}
      />
    );
  }
  const failing = failingRequired(evidence);
  const columns = Math.min(Math.max(evidence.checks.length, 2), 3) as 2 | 3;
  return (
    <section
      aria-labelledby={headingId}
      data-testid="evidence"
      className={cn("flex min-w-0 flex-col gap-2", className)}
    >
      <h3 id={headingId} className="text-caption font-medium text-muted-foreground">
        Checks on {evidence.node || "the change"}
      </h3>
      <StatStrip columns={columns}>
        {evidence.checks.map((check) => (
          <StatTile
            key={check.kind}
            label={CHECK_LABEL[check.kind]}
            value={<CheckBadge check={check} />}
            secondary={<CheckSummary check={check} />}
          />
        ))}
      </StatStrip>
      {failing.length > 0 ? (
        <p className="text-meta text-foreground-secondary" role="status">
          {evidence.roundsLeft > 0
            ? `${failing.map((c) => CHECK_LABEL[c.kind]).join(" and ")} failed. The writer goes again.`
            : `${failing.map((c) => CHECK_LABEL[c.kind]).join(" and ")} failed and the checks have no send-backs left: you decide.`}
        </p>
      ) : null}
      {evidence.checks.map((check) => (
        <CheckDetails key={check.kind} check={check} />
      ))}
    </section>
  );
}

function CheckBadge({ check }: { check: EvidenceCheck }) {
  const { status, label } = CHECK_BADGE[check.status];
  // The tile's value is a stat-sized figure; the badge keeps the badge size.
  return <StatusBadge status={status} label={label} className="text-caption" />;
}

function CheckSummary({ check }: { check: EvidenceCheck }) {
  return (
    <>
      {check.summary}
      {check.kind === "tests" && check.testMs !== null && check.testMs > 0 ? (
        <>
          {" · "}
          <Duration ms={check.testMs} />
        </>
      ) : null}
    </>
  );
}

/** The failing tests, or the findings the base does not have: a short list under the strip. */
function CheckDetails({ check }: { check: EvidenceCheck }) {
  if (check.kind === "tests" && check.failingTests.length > 0) {
    const shown = check.failingTests.slice(0, LISTED);
    return (
      <ul aria-label="Failing tests" className="flex flex-col gap-2 text-meta">
        {shown.map((test) => (
          <li
            key={`${test.file ?? ""}\u0000${test.name}`}
            className="flex min-w-0 flex-col gap-0.5"
          >
            <span className="font-mono text-caption break-words">{test.name}</span>
            {test.file ? <TruncatedPath path={test.file} focusable={false} /> : null}
            {test.message ? (
              <span className="line-clamp-2 break-words text-foreground-secondary">
                {test.message}
              </span>
            ) : null}
          </li>
        ))}
        {check.failingTests.length > LISTED ? (
          <li className="text-muted-foreground">and {check.failingTests.length - LISTED} more</li>
        ) : null}
      </ul>
    );
  }
  if (check.kind === "analyzers" && check.newFindings.length > 0) {
    const shown = check.newFindings.slice(0, LISTED);
    return (
      <ul aria-label="New findings" className="flex flex-col gap-2 text-meta">
        {shown.map((f) => (
          <li key={`${f.path}:${f.line ?? 0}:${f.rule}`} className="flex min-w-0 flex-col gap-0.5">
            <span className="font-mono text-caption break-words">
              {f.tool ? `${f.tool} ` : ""}
              {f.rule}
            </span>
            <TruncatedPath path={f.line ? `${f.path}:${f.line}` : f.path} focusable={false} />
            {f.message ? (
              <span className="line-clamp-2 break-words text-foreground-secondary">
                {f.message}
              </span>
            ) : null}
          </li>
        ))}
        {check.newFindings.length > LISTED ? (
          <li className="text-muted-foreground">and {check.newFindings.length - LISTED} more</li>
        ) : null}
      </ul>
    );
  }
  return null;
}
