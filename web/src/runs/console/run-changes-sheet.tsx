"use client";

import { FileDiffIcon } from "lucide-react";
import { useId, useState } from "react";

import { RelativeTime } from "@/components/display";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";

import { changeSets, useRunChanges, type ChangeSet } from "../use-run-changes";
import { GateReviewSheet } from "./gate-review-sheet";

/** How a change set is named in the picker: its key, and what kind of branch it is. */
export function changeSetLabel(set: ChangeSet): string {
  if (set.uncommitted) return `${set.key} · includes uncommitted work`;
  if (set.kind === "integration") return `${set.key} · integration branch`;
  return set.key;
}

/**
 * What a run's writers changed (12.3), read-only, from what was saved: so it is there once the
 * sandbox is gone. One writer at a time, with a picker when there are several; `only` shows one
 * writer key alone. A writer's uncommitted work, saved when the run failed or was cancelled,
 * stands for its branch: it holds the branch's commits too.
 */
export function RunChangesSheet({
  runId,
  open,
  onOpenChange,
  only,
  baseUrl,
}: {
  runId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  only?: string;
  baseUrl?: string;
}) {
  const pickerId = useId();
  const changes = useRunChanges(runId, { enabled: open, baseUrl });
  const [chosen, setChosen] = useState<string | null>(null);
  const sets = changes.data
    ? changeSets(changes.data).filter((s) => only === undefined || s.key === only)
    : [];
  const current = sets.find((s) => setId(s) === chosen) ?? sets[0] ?? null;

  let body = null;
  if (changes.isPending) {
    body = <LoadingState rows={4} label="Loading what the writers changed…" className="p-4" />;
  } else if (changes.isError) {
    body = (
      <ErrorState
        message={changes.error.message}
        onRetry={() => void changes.refetch()}
        className="p-4"
      />
    );
  } else if (!current) {
    body = (
      <EmptyState
        icon={FileDiffIcon}
        message="No writer changed a file."
        description="Nothing was committed or left uncommitted on a writer's branch."
        className="p-4"
      />
    );
  } else if (current.files === null) {
    body = (
      <div className="p-4">
        <Alert variant={current.error ? "destructive" : "default"}>
          <AlertDescription>
            {current.error
              ? `Its changes could not be read: ${current.error}`
              : "This branch was saved before changed files were recorded."}
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  return (
    <GateReviewSheet
      open={open}
      onOpenChange={onOpenChange}
      title={only ? `What ${only} changed` : "What the writers changed"}
      description="Read from the commits saved as each step ended, so it is kept after the run's sandbox is removed. The run's base is on the left."
      files={current?.files ?? []}
      body={body ?? undefined}
      notice={
        current ? (
          <div className="flex flex-col gap-2">
            {sets.length > 1 ? (
              <div className="flex flex-col gap-1">
                <label htmlFor={pickerId} className="text-caption text-muted-foreground">
                  Writer
                </label>
                <NativeSelect
                  id={pickerId}
                  className="w-full md:w-96"
                  value={setId(current)}
                  onChange={(e) => setChosen(e.target.value)}
                >
                  {sets.map((s) => (
                    <NativeSelectOption key={setId(s)} value={setId(s)}>
                      {changeSetLabel(s)}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
              </div>
            ) : null}
            <p className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-meta text-foreground-secondary">
              <span className="min-w-0 font-mono break-all text-foreground">{current.branch}</span>
              {current.uncommitted ? (
                <span>As it was on disk when the run ended, uncommitted work included</span>
              ) : (
                <span>
                  {current.commits} {current.commits === 1 ? "commit" : "commits"}
                </span>
              )}
              <RelativeTime iso={current.savedAt} prefix="saved " />
            </p>
            {current.bundleRemovedAt ? (
              <p className="text-meta text-foreground-secondary">
                Its saved commits were removed <RelativeTime iso={current.bundleRemovedAt} />; the
                files they changed are kept.
              </p>
            ) : null}
          </div>
        ) : undefined
      }
    />
  );
}

function setId(set: ChangeSet): string {
  return `${set.kind}:${set.key}`;
}
