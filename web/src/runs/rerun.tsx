"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { RotateCcwIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { apiBaseUrl, createApiClient } from "@/api/client";
import { ApiError } from "@/api/errors";
import type { components } from "@/api/schema";
import { IdChip, shortId } from "@/components/display";
import type { RunStatus } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { useWorkspaceId } from "@/workspace";

import { runsKey } from "./use-run-summaries";

/** Failed, cancelled and finished runs can be rerun; a live one cannot (the API answers 409). */
export function canRerun(status: RunStatus): boolean {
  return status === "failed" || status === "cancelled" || status === "succeeded";
}

/** Where a rerun from a step starts (12.4): the step, its changed parameters, and whether it
 * starts from the work it left uncommitted. */
export type RerunFrom = components["schemas"]["RerunFrom"];

/** A run to rerun: from the start, or from one of its steps (12.4). */
export type RerunTarget = string | { runId: string; from: RerunFrom };

/** Reruns a run: a new run with its workflow, input and repo, linked by `rerun_of`, from the
 * start or from one of its steps. Opens the new run, with a toast naming the one it repeats. */
export function useRerun({
  baseUrl = apiBaseUrl(),
  workspaceId: givenWorkspaceId,
  navigate,
}: {
  baseUrl?: string;
  workspaceId?: string;
  navigate?: (url: string) => void;
} = {}) {
  const workspaceId = useWorkspaceId(givenWorkspaceId);
  const router = useRouter();
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (target: RerunTarget) => {
      const runId = typeof target === "string" ? target : target.runId;
      let result;
      try {
        result = await createApiClient(baseUrl).POST("/runs/{run_id}/rerun", {
          params: { path: { run_id: runId } },
          ...(typeof target === "string" ? {} : { body: { from: target.from } }),
        });
      } catch {
        throw new Error("Could not reach the API.");
      }
      const { data, error, response } = result;
      if (!data) throw new ApiError(response.status, error, "The run could not be rerun");
      return data.run_id;
    },
    onSuccess: (newId, target) => {
      void queries.invalidateQueries({ queryKey: runsKey(workspaceId) });
      if (typeof target === "string") toast.success(`Started a rerun of ${shortId(target)}`);
      else toast.success(`Started a rerun of ${shortId(target.runId)} from ${target.from.node_id}`);
      const url = `/runs/${newId}`;
      if (navigate) navigate(url);
      else router.push(url);
    },
    onError: (error) => toast.error(error.message),
  });
}

/** The console header's Rerun: primary on a failed or cancelled run, secondary on a finished one. */
export function RerunButton({
  runId,
  status,
  baseUrl,
}: {
  runId: string;
  status: RunStatus;
  baseUrl?: string;
}) {
  const rerun = useRerun({ baseUrl });
  return (
    <Button
      type="button"
      size="sm"
      variant={status === "succeeded" ? "outline" : "default"}
      disabled={rerun.isPending}
      onClick={() => rerun.mutate(runId)}
    >
      <RotateCcwIcon aria-hidden="true" data-icon="inline-start" />
      {rerun.isPending ? "Starting…" : "Rerun"}
    </Button>
  );
}

/** "Rerun of abcd1234", and "from review" for a rerun from a step (12.4): a link to the run
 * this one repeats. */
export function RerunOf({
  runId,
  fromStep,
  className,
}: {
  runId: string;
  fromStep?: string | null;
  className?: string;
}) {
  return (
    <span className={className}>
      Rerun of <IdChip id={runId} label="run" href={`/runs/${runId}`} className="relative z-10" />
      {fromStep ? (
        <>
          {" "}
          from <span className="font-mono">{fromStep}</span>
        </>
      ) : null}
    </span>
  );
}
