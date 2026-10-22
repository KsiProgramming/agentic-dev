"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { RotateCcwIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { apiBaseUrl, createApiClient } from "@/api/client";
import { ApiError } from "@/api/errors";
import type { RunStatus } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { DEFAULT_WORKSPACE_ID } from "@/workspace";

import { runsKey } from "./use-run-summaries";

/** Failed, cancelled and finished runs can be rerun; a live one cannot (the API answers 409). */
export function canRerun(status: RunStatus): boolean {
  return status === "failed" || status === "cancelled" || status === "succeeded";
}

/** Reruns a run: a new run with its workflow, input and repo, linked by `rerun_of`. Opens the
 * new run, with a toast naming the one it repeats. */
export function useRerun({
  baseUrl = apiBaseUrl(),
  workspaceId = DEFAULT_WORKSPACE_ID,
  navigate,
}: {
  baseUrl?: string;
  workspaceId?: string;
  navigate?: (url: string) => void;
} = {}) {
  const router = useRouter();
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (runId: string) => {
      let result;
      try {
        result = await createApiClient(baseUrl).POST("/runs/{run_id}/rerun", {
          params: { path: { run_id: runId } },
        });
      } catch {
        throw new Error("Could not reach the API.");
      }
      const { data, error, response } = result;
      if (!data) throw new ApiError(response.status, error, "The run could not be rerun");
      return data.run_id;
    },
    onSuccess: (newId, runId) => {
      void queries.invalidateQueries({ queryKey: runsKey(workspaceId) });
      toast.success(`Started a rerun of ${runId.slice(0, 8)}`);
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

/** "Rerun of abcd1234": a link to the run this one repeats. */
export function RerunOf({ runId, className }: { runId: string; className?: string }) {
  return (
    <span className={className}>
      Rerun of{" "}
      <Link
        href={`/runs/${runId}`}
        className="relative z-10 rounded-sm font-mono text-primary underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        {runId.slice(0, 8)}
      </Link>
    </span>
  );
}
