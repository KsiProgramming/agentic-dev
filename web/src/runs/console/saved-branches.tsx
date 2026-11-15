"use client";

import { FileDiffIcon, GitCommitHorizontalIcon } from "lucide-react";
import { useState } from "react";

import { IdChip, RelativeTime } from "@/components/display";
import { Button } from "@/components/ui/button";

import type { SavedBranch } from "../timeline";
import { RunChangesSheet } from "./run-changes-sheet";
import { ErrorLine } from "./step-view";

function commitsLabel(n: number): string {
  return `${n} ${n === 1 ? "commit" : "commits"}`;
}

/**
 * The branches a step's writers committed on, saved outside the sandbox (12.2): each with how
 * many commits it holds, its tip and when it was saved, so a lost sandbox loses none of it. A
 * branch whose last save failed says why: its newer commits are only in the sandbox. "View
 * changes" shows what a branch changed, from what was saved (12.3), so after its sandbox is gone.
 */
export function SavedBranches({
  branches,
  runId,
  baseUrl,
}: {
  branches: SavedBranch[];
  runId: string;
  baseUrl?: string;
}) {
  const [shown, setShown] = useState<string | null>(null);
  return (
    <section
      aria-label="Commits saved"
      data-testid="saved-branches"
      className="flex flex-col gap-2"
    >
      <h3 className="text-caption font-medium text-muted-foreground">Commits saved</h3>
      <ul className="flex flex-col gap-2">
        {branches.map((saved) => (
          <li key={saved.branch} className="flex min-w-0 flex-col gap-1">
            {saved.head !== null && saved.commits !== null ? (
              <p className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-meta text-foreground-secondary">
                <GitCommitHorizontalIcon
                  aria-hidden="true"
                  className="size-4 shrink-0 text-muted-foreground"
                />
                <span className="min-w-0 font-mono break-all text-foreground">{saved.branch}</span>
                <span>{commitsLabel(saved.commits)}</span>
                <IdChip id={saved.head} label="commit" />
                {saved.error === null ? <RelativeTime iso={saved.at} prefix="saved " /> : null}
                <Button
                  type="button"
                  variant="link"
                  size="sm"
                  className="h-auto p-0"
                  aria-label={`View changes on ${saved.branch}`}
                  onClick={() => setShown(saved.key)}
                >
                  <FileDiffIcon aria-hidden="true" data-icon="inline-start" />
                  View changes
                </Button>
              </p>
            ) : (
              <p className="min-w-0 font-mono text-meta break-all text-foreground">
                {saved.branch}
              </p>
            )}
            {saved.error !== null ? (
              <ErrorLine
                error={`Not saved: ${saved.error}. Its newer commits are only in the sandbox.`}
              />
            ) : null}
          </li>
        ))}
      </ul>
      <RunChangesSheet
        runId={runId}
        open={shown !== null}
        onOpenChange={(open) => {
          if (!open) setShown(null);
        }}
        only={shown ?? undefined}
        baseUrl={baseUrl}
      />
    </section>
  );
}
