import { FlaskConicalIcon } from "lucide-react";
import { useId } from "react";

import { Duration, Percent, StatStrip, StatTile, TruncatedPath } from "@/components/display";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { StatusBadge, type RunStatus } from "@/components/status-badge";
import { cn } from "@/lib/utils";

import { reviewHeadline, reviewOutcome, type Review, type ReviewOutcome } from "../review";
import {
  CHECK_BADGE,
  CHECK_LABEL,
  CRITERION_BADGE,
  beforeAfter,
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
  review = null,
  loading = false,
  error,
  onRetry,
  className,
}: {
  evidence: Evidence | null;
  /** What the independent review found (13.6): one more tile, with its outcome. */
  review?: Review | null;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  className?: string;
}) {
  const headingId = useId();
  if (loading) return <LoadingState rows={2} label="Loading the checks…" className={className} />;
  if (error) return <ErrorState message={error} onRetry={onRetry} className={className} />;
  if (!evidence && !review) return null;
  if (!evidence || evidence.checks.length === 0) {
    if (review) return <ReviewTile review={review} className={className} />;
    return (
      <EmptyState
        icon={FlaskConicalIcon}
        message="No checks ran for this change."
        className={className}
      />
    );
  }
  const failing = failingRequired(evidence);
  // Build, tests and analyzers are one strip; coverage and criteria (13.4) another, so five
  // checks never leave an empty cell in a row.
  const basic = evidence.checks.filter((c) => c.kind !== "coverage" && c.kind !== "criteria");
  const judged = evidence.checks.filter((c) => c.kind === "coverage" || c.kind === "criteria");
  const groups = [basic, judged].filter((g) => g.length > 0);
  return (
    <section
      aria-labelledby={headingId}
      data-testid="evidence"
      className={cn("flex min-w-0 flex-col gap-2", className)}
    >
      <h3 id={headingId} className="text-caption font-medium text-muted-foreground">
        Checks on {evidence.node || "the change"}
      </h3>
      {groups.map((group) => (
        <StatStrip key={group[0].kind} columns={Math.min(Math.max(group.length, 2), 3) as 2 | 3}>
          {group.map((check) => (
            <StatTile
              key={check.kind}
              label={CHECK_LABEL[check.kind]}
              value={<CheckValue check={check} />}
              secondary={<CheckSummary check={check} />}
            />
          ))}
        </StatStrip>
      ))}
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
      {review ? <ReviewTile review={review} /> : null}
    </section>
  );
}

const REVIEW_BADGE: Record<ReviewOutcome, { status: RunStatus; label: string }> = {
  passed: { status: "succeeded", label: "Passed" },
  sent_back: { status: "failed", label: "Sent back" },
  could_not_run: { status: "failed", label: "Could not run" },
  blocking: { status: "waiting", label: "Needs a decision" },
};

/**
 * The independent review (13.6) as one tile: its outcome as a `StatusBadge` (Passed, Sent back,
 * Could not run) and "2 high · 5 comments" under it. It is a strip of its own with one cell
 * across the whole width, so it never leaves an empty cell beside the checks. The comments
 * themselves are `ReviewComments`.
 */
export function ReviewTile({ review, className }: { review: Review; className?: string }) {
  const headingId = useId();
  const outcome = reviewOutcome(review);
  const { status, label } = REVIEW_BADGE[outcome];
  const failed = review.failedLenses.length;
  return (
    <section
      aria-labelledby={headingId}
      data-testid="review-tile"
      className={cn("flex min-w-0 flex-col gap-2", className)}
    >
      <h3 id={headingId} className="sr-only">
        Independent review of {review.from}
      </h3>
      <StatStrip columns={2} className="md:grid-cols-1">
        <StatTile
          label="Review"
          value={<StatusBadge status={status} label={label} className="text-caption" />}
          secondary={
            <>
              {reviewHeadline(review)}
              {failed > 0 ? ` · ${failed} ${failed === 1 ? "lens" : "lenses"} could not run` : ""}
            </>
          }
        />
      </StatStrip>
      {outcome === "sent_back" ? (
        <p className="text-meta text-foreground-secondary" role="status">
          {review.roundsLeft > 0
            ? "The review found blocking comments. The writer goes again."
            : "The review found blocking comments and has no send-backs left: you decide."}
        </p>
      ) : null}
    </section>
  );
}

function CheckBadge({ check }: { check: EvidenceCheck }) {
  const { status, label } = CHECK_BADGE[check.status];
  // The tile's value is a stat-sized figure; the badge keeps the badge size.
  return <StatusBadge status={status} label={label} className="text-caption" />;
}

/** A tile's value: the outcome as a badge, and for coverage and criteria the figure beside it
 * (the share of changed lines the tests ran, how many criteria are proven). */
function CheckValue({ check }: { check: EvidenceCheck }) {
  if (check.kind === "coverage" && check.coverage && check.coverage.changed > 0) {
    return (
      <span className="flex min-w-0 items-center gap-2">
        <Percent value={check.coverage.percent / 100} />
        <CheckBadge check={check} />
      </span>
    );
  }
  if (check.kind === "criteria" && check.criteria.length > 0) {
    const proven = check.criteria.filter((c) => c.state === "proven").length;
    return (
      <span className="flex min-w-0 items-center gap-2">
        <span>
          {proven} of {check.criteria.length}
        </span>
        <CheckBadge check={check} />
      </span>
    );
  }
  return <CheckBadge check={check} />;
}

function CheckSummary({ check }: { check: EvidenceCheck }) {
  return (
    <>
      {check.kind === "coverage" && check.coverage && check.coverage.changed > 0
        ? `${check.coverage.covered} of ${check.coverage.changed} changed lines · needs ${check.coverage.threshold}%`
        : check.summary}
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
  if (check.kind === "criteria" && check.criteria.length > 0) {
    const shown = check.criteria.slice(0, LISTED);
    return (
      <ul aria-label="Acceptance criteria" className="flex flex-col gap-2 text-meta">
        {shown.map((c) => {
          const { status, label } = CRITERION_BADGE[c.state];
          const words = beforeAfter(c);
          return (
            <li key={c.id} className="flex min-w-0 flex-col gap-0.5">
              <span className="flex min-w-0 flex-wrap items-center gap-2">
                <span className="font-mono text-caption">{c.id}</span>
                <StatusBadge status={status} label={label} className="text-caption" />
                {words ? <span className="text-foreground-secondary">{words}</span> : null}
              </span>
              {c.tests.slice(0, 3).map((t) => (
                <span key={t.name} className="font-mono text-caption break-words">
                  {t.name}
                </span>
              ))}
            </li>
          );
        })}
        {check.criteria.length > LISTED ? (
          <li className="text-muted-foreground">and {check.criteria.length - LISTED} more</li>
        ) : null}
      </ul>
    );
  }
  if (check.kind === "coverage" && check.coverage) {
    const missed = check.coverage.files.filter((f) => f.uncovered.length > 0);
    if (missed.length === 0) return null;
    const shown = missed.slice(0, LISTED);
    return (
      <ul aria-label="Uncovered lines" className="flex flex-col gap-2 text-meta">
        {shown.map((f) => (
          <li key={f.path} className="flex min-w-0 flex-col gap-0.5">
            <TruncatedPath path={f.path} focusable={false} />
            <span className="text-foreground-secondary">
              no test runs lines{" "}
              {f.uncovered.map(([a, b]) => (a === b ? a : `${a}-${b}`)).join(", ")}
            </span>
          </li>
        ))}
        {missed.length > LISTED ? (
          <li className="text-muted-foreground">and {missed.length - LISTED} more</li>
        ) : null}
      </ul>
    );
  }
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
