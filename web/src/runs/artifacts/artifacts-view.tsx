"use client";

import { FileJsonIcon, FileTextIcon, PackageOpenIcon } from "lucide-react";
import { useState } from "react";

import { apiBaseUrl } from "@/api/client";
import { RelativeTime } from "@/components/display";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";

import { ArtifactSheet, artifactFacts } from "./artifact-cards";
import { artifactKind, type ArtifactVersion } from "./artifacts";
import { useRunArtifacts, type RunArtifact } from "./use-run-artifacts";

function versionOf(artifact: RunArtifact): ArtifactVersion {
  return {
    name: artifact.name,
    version: artifact.version,
    nodeId: artifact.node_id,
    mediaType: artifact.media_type,
    size: artifact.size,
  };
}

/**
 * The run's artifacts (4.3), the console's third view beside Steps and Graph: each artifact's
 * latest version, the step that wrote it, how many versions there are and when it was written.
 * Selecting one opens its content; its writer opens that step.
 */
export function ArtifactsView({
  runId,
  written,
  live,
  now,
  onOpenStep,
  baseUrl = apiBaseUrl(),
}: {
  runId: string;
  /** How many `artifact_written` events the page has, so the list follows the run. */
  written: number;
  live: boolean;
  now: number;
  onOpenStep: (nodeId: string) => void;
  baseUrl?: string;
}) {
  const query = useRunArtifacts(runId, written, baseUrl);
  const [open, setOpen] = useState<ArtifactVersion | null>(null);

  if (query.isPending) return <LoadingState rows={3} label="Loading the artifacts…" />;
  if (!query.data) {
    return (
      <ErrorState
        message={query.error?.message ?? "Could not load the artifacts."}
        onRetry={() => void query.refetch()}
      />
    );
  }
  if (query.data.length === 0) {
    return (
      <EmptyState
        icon={PackageOpenIcon}
        message={live ? "No artifacts yet." : "This run wrote no artifacts."}
      />
    );
  }
  return (
    <>
      <ul aria-label="Run artifacts" className="flex flex-col divide-y rounded-lg border">
        {query.data.map((artifact) => {
          const version = versionOf(artifact);
          const Icon = artifactKind(version) === "JSON" ? FileJsonIcon : FileTextIcon;
          return (
            <li
              key={artifact.name}
              data-testid="run-artifact"
              className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2"
            >
              <button
                type="button"
                onClick={() => setOpen(version)}
                className="flex min-w-0 flex-1 items-center gap-2 rounded-md text-left outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring/50"
              >
                <Icon aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
                <span className="flex min-w-0 flex-col">
                  <span className="truncate font-mono text-meta">{artifact.name}</span>
                  <span className="text-caption text-muted-foreground tabular-nums">
                    {artifactFacts(version)}
                    {artifact.versions > 1 ? ` of ${artifact.versions}` : ""}
                  </span>
                </span>
              </button>
              <span className="flex items-center gap-2 text-caption text-muted-foreground">
                <span>by</span>
                <button
                  type="button"
                  onClick={() => onOpenStep(artifact.node_id)}
                  className="rounded-sm font-mono text-primary underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring/50"
                >
                  {artifact.node_id}
                </button>
                <RelativeTime iso={artifact.created_at} now={now} focusable={false} />
              </span>
            </li>
          );
        })}
      </ul>
      <ArtifactSheet
        runId={runId}
        artifact={open}
        onClose={() => setOpen(null)}
        baseUrl={baseUrl}
      />
    </>
  );
}
