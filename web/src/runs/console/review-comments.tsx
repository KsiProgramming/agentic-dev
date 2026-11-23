"use client";

import { CircleXIcon, MessageSquareTextIcon, ShieldAlertIcon, UndoIcon, XIcon } from "lucide-react";
import { useId } from "react";

import { TruncatedPath } from "@/components/display";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { SeverityBadge } from "../findings/findings-view";
import {
  commentLocation,
  lensList,
  splitComments,
  type Review,
  type ReviewComment,
} from "../review";

/** The comments of each file, in the order the review gave them (most severe first). */
function byFile(comments: ReviewComment[]): [string, ReviewComment[]][] {
  const files = new Map<string, ReviewComment[]>();
  for (const comment of comments) {
    files.set(comment.path, [...(files.get(comment.path) ?? []), comment]);
  }
  return [...files];
}

interface RowProps {
  /** The fingerprints dismissed so far. */
  dismissed?: ReadonlySet<string>;
  /** Present while the gate waits: makes each comment dismissable. */
  onToggleDismiss?: (fingerprint: string) => void;
  /** Opens the comment's file at its line in the diff. */
  onSelect?: (comment: ReviewComment) => void;
}

/**
 * The independent review's comments (13.6, tech-stack → Gate evidence → Review comments),
 * grouped by file: each row has the severity, where it is (`path:line`), the lenses that made it
 * (mono), the message and "Blocking" when it blocks. On a waiting gate (`onToggleDismiss`) every
 * row has a Dismiss toggle (`aria-pressed`); a decided gate shows what was dismissed. Selecting a
 * row's location (`onSelect`) opens that file at that line in the diff: the list is the keyboard
 * and screen-reader path, the diff's comments a convenience. Comments on files the change did
 * not touch are listed apart. Messages are the reviewers' words: text, never markup. It has the
 * three states of a data view.
 */
export function ReviewComments({
  review,
  loading = false,
  error,
  onRetry,
  className,
  ...rows
}: {
  review: Review | null;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  className?: string;
} & RowProps) {
  const headingId = useId();
  if (loading) {
    return <LoadingState rows={3} label="Loading the review…" className={className} />;
  }
  if (error) return <ErrorState message={error} onRetry={onRetry} className={className} />;
  if (!review) return null;
  const { inDiff, apart } = splitComments(review);
  if (review.comments.length === 0 && review.failedLenses.length === 0) {
    return (
      <EmptyState
        icon={MessageSquareTextIcon}
        message="The reviewers had nothing to say about this change."
        className={className}
      />
    );
  }
  return (
    <section
      aria-labelledby={headingId}
      data-testid="review-comments"
      className={cn("flex min-w-0 flex-col gap-3", className)}
    >
      <h3 id={headingId} className="text-caption font-medium text-muted-foreground">
        Review comments
      </h3>
      {review.failedLenses.map((lens) => (
        <p
          key={lens}
          role="status"
          className="flex items-center gap-1.5 text-meta text-status-failed"
        >
          <CircleXIcon aria-hidden="true" className="size-4 shrink-0" />
          The {lens.replace(/^review_/, "")} lens could not run.
        </p>
      ))}
      {byFile(inDiff).map(([path, comments]) => (
        <FileGroup key={path} path={path} comments={comments} {...rows} />
      ))}
      {apart.length > 0 ? (
        <section aria-label="Files the change did not touch" className="flex flex-col gap-2">
          <h4 className="text-caption font-medium text-muted-foreground">
            Files the change did not touch
          </h4>
          {byFile(apart).map(([path, comments]) => (
            // A file the change did not touch has no diff to open.
            <FileGroup key={path} path={path} comments={comments} {...rows} onSelect={undefined} />
          ))}
        </section>
      ) : null}
      {review.truncated ? (
        <p className="text-meta text-muted-foreground">
          Only the first {review.comments.length} comments are shown.
        </p>
      ) : null}
    </section>
  );
}

function FileGroup({
  path,
  comments,
  dismissed,
  onToggleDismiss,
  onSelect,
}: { path: string; comments: ReviewComment[] } & RowProps) {
  return (
    <div role="group" aria-label={path} className="flex min-w-0 flex-col gap-1.5">
      <TruncatedPath path={path} focusable={false} />
      <ul className="flex flex-col divide-y divide-divider rounded-lg border">
        {comments.map((comment) => (
          <CommentRow
            key={comment.fingerprint}
            comment={comment}
            dismissed={dismissed?.has(comment.fingerprint) ?? false}
            onToggleDismiss={onToggleDismiss}
            onSelect={onSelect}
          />
        ))}
      </ul>
    </div>
  );
}

function CommentRow({
  comment,
  dismissed,
  onToggleDismiss,
  onSelect,
}: {
  comment: ReviewComment;
  dismissed: boolean;
} & Pick<RowProps, "onToggleDismiss" | "onSelect">) {
  const where = commentLocation(comment);
  return (
    <li
      data-testid="review-comment"
      data-dismissed={dismissed ? "true" : undefined}
      className="flex min-w-0 flex-col gap-1.5 px-3 py-2"
    >
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <SeverityBadge severity={comment.severity} />
        {comment.blocking ? (
          <Badge variant="outline">
            <ShieldAlertIcon aria-hidden="true" />
            Blocking
          </Badge>
        ) : null}
        {onSelect ? (
          <button
            type="button"
            onClick={() => onSelect(comment)}
            aria-label={`Show ${where} in the diff`}
            className="min-w-0 flex-1 basis-32 cursor-pointer rounded-sm text-left outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <TruncatedPath path={where} focusable={false} />
          </button>
        ) : (
          <TruncatedPath path={where} focusable={false} className="min-w-0 flex-1 basis-32" />
        )}
        {onToggleDismiss ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-pressed={dismissed}
            aria-label={`Dismiss the comment on ${where}`}
            onClick={() => onToggleDismiss(comment.fingerprint)}
          >
            {dismissed ? (
              <UndoIcon aria-hidden="true" data-icon="inline-start" />
            ) : (
              <XIcon aria-hidden="true" data-icon="inline-start" />
            )}
            {dismissed ? "Dismissed" : "Dismiss"}
          </Button>
        ) : dismissed ? (
          <span className="text-caption text-muted-foreground">Dismissed</span>
        ) : null}
      </div>
      {comment.lenses.length > 0 ? (
        <p className="font-mono text-caption text-foreground-secondary">
          {lensList(comment.lenses)}
        </p>
      ) : null}
      {/* The reviewer's words are data: text, never markup. */}
      <p className={cn("break-words whitespace-pre-wrap", dismissed && "line-through")}>
        {comment.message}
      </p>
    </li>
  );
}
