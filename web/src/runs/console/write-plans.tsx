"use client";

import {
  ExternalLinkIcon,
  FolderPlusIcon,
  GitPullRequestIcon,
  MessageSquareIcon,
  MoveRightIcon,
  PackageCheckIcon,
  type LucideIcon,
} from "lucide-react";
import { useId, useState } from "react";

import { TruncatedPath } from "@/components/display";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { transitionOf, type PlanAction, type WriteCheck, type WritePlan } from "../plans";
import { AgentMessage } from "./agent-message";
import { isLongOutput } from "./long-output";

/** One icon per kind of write; they are decoration, the summary says what it is. */
const ICON: Record<PlanAction, LucideIcon> = {
  open_pr: GitPullRequestIcon,
  push_to_pr: GitPullRequestIcon,
  create_repo: FolderPlusIcon,
  comment: MessageSquareIcon,
  transition: MoveRightIcon,
};

/** The comment or pull request text as sanitised Markdown (raw HTML and images are dropped),
 * capped like an agent's answer until "Show full". It is data, never a page. */
function PlanBody({ text }: { text: string }) {
  const [full, setFull] = useState(false);
  const id = useId();
  const long = isLongOutput(text);
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div
        id={id}
        data-testid="plan-body"
        className={cn(
          "rounded-md border bg-surface-subtle p-3",
          long && !full && "max-h-64 overflow-hidden",
        )}
      >
        <AgentMessage text={text} />
      </div>
      {long ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="w-fit"
          aria-expanded={full}
          aria-controls={id}
          onClick={() => setFull((f) => !f)}
        >
          {full ? "Show less" : "Show full"}
        </Button>
      ) : null}
    </div>
  );
}

/** What the write acts on: the repo or pull request in the mono font, an issue key in mono and
 * linked only when its address is https. */
function Target({ plan }: { plan: WritePlan }) {
  const { label, url, kind } = plan.target;
  const name = <span className="font-mono text-meta">{label}</span>;
  if (url && kind === "issue") {
    return (
      <a
        href={url}
        target="_blank"
        rel="noreferrer"
        className="inline-flex w-fit items-center gap-1 text-foreground underline-offset-4 hover:underline"
      >
        {name}
        <ExternalLinkIcon aria-hidden="true" className="size-3 shrink-0" />
        <span className="sr-only">(opens in a new tab)</span>
      </a>
    );
  }
  return name;
}

/** A pull request's branch and base, and how many commits go. */
function Branches({ plan }: { plan: WritePlan }) {
  const head = typeof plan.fields.head === "string" ? plan.fields.head : null;
  const base = typeof plan.fields.base === "string" ? plan.fields.base : null;
  const commits = typeof plan.fields.commits === "number" ? plan.fields.commits : null;
  if (!head) return null;
  return (
    <p className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 text-meta text-foreground-secondary">
      <TruncatedPath path={head} focusable={false} className="min-w-0 basis-40" />
      {base ? (
        <>
          <MoveRightIcon aria-hidden="true" className="size-4 shrink-0" />
          <span className="sr-only">into</span>
          <span className="font-mono">{base}</span>
        </>
      ) : null}
      {commits !== null ? (
        <span>
          · {commits} {commits === 1 ? "commit" : "commits"}
        </span>
      ) : null}
    </p>
  );
}

function PlanCard({ plan }: { plan: WritePlan }) {
  const Icon = ICON[plan.action];
  const move = transitionOf(plan);
  const title = typeof plan.fields.title === "string" ? plan.fields.title : null;
  return (
    <li
      data-testid="write-plan"
      data-action={plan.action}
      className="flex min-w-0 flex-col gap-2 rounded-lg border bg-card p-3"
    >
      <div className="flex min-w-0 flex-wrap items-start gap-x-2 gap-y-1">
        <Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-foreground-secondary" />
        <p className="min-w-0 flex-1 basis-48 text-meta font-medium break-words">{plan.summary}</p>
        {plan.error ? <StatusBadge status="failed" label="Would fail" /> : null}
      </div>
      <div className="flex min-w-0 flex-col gap-1 pl-6">
        <p className="flex min-w-0 flex-wrap items-center gap-x-1.5 text-meta text-foreground-secondary">
          <Target plan={plan} />
        </p>
        {move ? (
          <p data-testid="plan-transition" className="text-meta text-foreground-secondary">
            {move.from} → {move.to}
          </p>
        ) : null}
        {plan.action === "open_pr" || plan.action === "push_to_pr" ? (
          <Branches plan={plan} />
        ) : null}
        {title ? <p className="text-meta text-foreground">{title}</p> : null}
        {plan.error ? (
          <p data-testid="plan-error" className="text-meta text-status-failed">
            <span className="font-mono">{plan.error.code}</span>: {plan.error.message}
          </p>
        ) : null}
        {plan.body ? <PlanBody text={plan.body} /> : null}
        {plan.pending.map((part) => (
          <p
            key={part.kind}
            data-testid="plan-pending"
            className="text-meta text-foreground-secondary"
          >
            {part.text}
          </p>
        ))}
      </div>
    </li>
  );
}

/**
 * What approving does (tech-stack → UI design system → What approving does): one card per
 * outward write the gate guards, as its tool planned it without doing it. Each card has an icon
 * for its kind, the summary, what the write acts on (a repo or an issue key in the mono font), a
 * transition as "from → to", the comment or pull request text as sanitised Markdown capped with
 * "Show full", and a quiet line for what the platform adds only after the approval (links,
 * review notes). A write that would fail now says so with a status badge and the error as text.
 * Nothing renders without plans; a caller that loads them itself passes `loading` and `error`.
 */
export function WritePlans({
  plans,
  loading = false,
  error,
  onRetry,
  empty = false,
  className,
}: {
  plans: WritePlan[];
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  /** Show the empty state when there are no plans, instead of nothing. */
  empty?: boolean;
  className?: string;
}) {
  const headingId = useId();
  if (loading) return <LoadingState rows={3} label="Loading the plans…" className={className} />;
  if (error) return <ErrorState message={error} onRetry={onRetry} className={className} />;
  if (plans.length === 0) {
    return empty ? (
      <EmptyState
        icon={PackageCheckIcon}
        message="Approving writes nothing outside the run."
        className={className}
      />
    ) : null;
  }
  return (
    <section
      aria-labelledby={headingId}
      data-testid="write-plans"
      className={cn("flex min-w-0 flex-col gap-2", className)}
    >
      <h3 id={headingId} className="text-caption font-medium text-muted-foreground">
        What approving does
      </h3>
      <ul className="flex min-w-0 flex-col gap-2">
        {plans.map((plan, i) => (
          <PlanCard key={`${plan.nodeId ?? plan.tool}:${i}`} plan={plan} />
        ))}
      </ul>
    </section>
  );
}

/**
 * How an outward write went against the plan its gate showed (13.8), in the write's own step: a
 * quiet "As planned at <gate>", or a `StatusBadge` "Not as planned" (or "Plan out of date" for a
 * write the tool refused because what it was planned against changed, which wrote nothing) with
 * each difference as text: the field, what was planned and what happened.
 */
export function WriteChecked({ check, className }: { check: WriteCheck; className?: string }) {
  if (check.outcome === "as_planned") {
    return (
      <p
        data-testid="write-checked"
        className={cn("text-meta text-foreground-secondary", className)}
      >
        As planned{check.gate ? " at " : ""}
        {check.gate ? <span className="font-mono">{check.gate}</span> : null}
      </p>
    );
  }
  return (
    <div data-testid="write-checked" className={cn("flex min-w-0 flex-col gap-2", className)}>
      <StatusBadge
        status="failed"
        label={check.outcome === "stale" ? "Plan out of date" : "Not as planned"}
        className="w-fit"
      />
      {check.differences.length > 0 ? (
        <ul aria-label="Differences from the plan" className="flex flex-col gap-1">
          {check.differences.map((d) => (
            <li key={d.field} className="min-w-0 text-meta break-words text-foreground-secondary">
              <span className="font-mono">{d.field}</span>: planned {d.planned}, was {d.actual}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
