"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiBaseUrl, createApiClient } from "@/api/client";
import { ApiError, detailOf } from "@/api/errors";
import type { components } from "@/api/schema";
import { useDebounced } from "@/lib/use-debounced";

import type { GraphOp } from "./ops";

/** One stored version of a workflow (5.1), with why it could not run now. */
export type WorkflowVersion = components["schemas"]["WorkflowVersionResponse"];

export function workflowKey(workspaceId: string, workflowId: string) {
  return ["workspace", workspaceId, "workflow", workflowId] as const;
}

/** Fetch errors become "Could not reach the API." instead of the browser's TypeError. */
async function call<T>(request: () => Promise<T>): Promise<T> {
  try {
    return await request();
  } catch (err) {
    throw err instanceof TypeError ? new Error("Could not reach the API.") : err;
  }
}

/** `GET /workflows/{id}`: the latest version; `null` when there is no such workflow. */
export async function fetchWorkflow(
  baseUrl: string,
  workspaceId: string,
  workflowId: string,
): Promise<WorkflowVersion | null> {
  const { data, error, response } = await call(() =>
    createApiClient(baseUrl).GET("/workflows/{workflow_id}", {
      params: { path: { workflow_id: workflowId }, query: { workspace_id: workspaceId } },
    }),
  );
  if (response.status === 404) return null;
  if (!data) throw new ApiError(response.status, error, "Could not load the workflow");
  return data;
}

/** The workflow's latest version. It is not refetched on focus: the builder's unsaved edits are
 * made against it, and a newer version is met on Save (`409`). */
export function useWorkflow(workspaceId: string, workflowId: string, baseUrl = apiBaseUrl()) {
  return useQuery({
    queryKey: workflowKey(workspaceId, workflowId),
    queryFn: () => fetchWorkflow(baseUrl, workspaceId, workflowId),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
}

/** Why a workflow cannot run, on the node to fix (3.4). */
export type ValidationIssue = components["schemas"]["ValidationIssue"];

/** How long the builder waits after the last edit before it checks the edited spec. */
export const VALIDATE_DEBOUNCE_MS = 400;

/** The issues of the workflow as edited (5.6): the version's own while there are no unsaved
 * edits; otherwise `POST /workflows/{id}/validate` on `spec`, once it has not changed for
 * `VALIDATE_DEBOUNCE_MS`, keeping the last answer meanwhile. A failed check blocks nothing. */
export function useValidation(
  workspaceId: string,
  version: WorkflowVersion,
  spec: unknown,
  dirty: boolean,
  baseUrl = apiBaseUrl(),
) {
  const checked = useDebounced(dirty ? spec : null, VALIDATE_DEBOUNCE_MS);
  const query = useQuery({
    queryKey: [...workflowKey(workspaceId, version.workflow_id), "validate", checked],
    queryFn: async () => {
      const { data, error, response } = await call(() =>
        createApiClient(baseUrl).POST("/workflows/{workflow_id}/validate", {
          params: { path: { workflow_id: version.workflow_id } },
          body: {
            workflow: checked as components["schemas"]["ValidateWorkflowRequest"]["workflow"],
            workspace_id: workspaceId,
          },
        }),
      );
      if (!data) throw new ApiError(response.status, error, "Could not check the workflow");
      return data;
    },
    enabled: dirty && checked !== null,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  if (!dirty) {
    return { issues: version.issues, checking: false, error: null, retry: () => {} };
  }
  return {
    issues: query.data?.issues ?? version.issues,
    checking: checked !== spec || query.isFetching,
    error: query.isError ? "Could not check the workflow." : null,
    retry: () => void query.refetch(),
  };
}

/** `PATCH /workflows/{id}`: the ops applied to `base_version`, stored as the next version. A
 * refusal is an `ApiError` whose body is `version_conflict` (409) or the op's error (422). */
export function useSaveWorkflow(workspaceId: string, workflowId: string, baseUrl = apiBaseUrl()) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ baseVersion, ops }: { baseVersion: number; ops: GraphOp[] }) => {
      const { data, error, response } = await call(() =>
        createApiClient(baseUrl).PATCH("/workflows/{workflow_id}", {
          params: { path: { workflow_id: workflowId }, query: { workspace_id: workspaceId } },
          body: { base_version: baseVersion, ops },
        }),
      );
      if (!data) throw new ApiError(response.status, error, "Could not save the workflow");
      return data;
    },
    onSuccess: (version) => {
      queryClient.setQueryData(workflowKey(workspaceId, workflowId), version);
    },
  });
}

/** `POST /workflows` from a template with its defaults; the id of the workflow to open, the
 * existing one when the workspace already has it (`workflow_exists`). */
export function useWorkflowFromTemplate(workspaceId: string, baseUrl = apiBaseUrl()) {
  return useMutation({
    mutationFn: async (templateId: string): Promise<string> => {
      const { data, error, response } = await call(() =>
        createApiClient(baseUrl).POST("/workflows", {
          params: { query: { workspace_id: workspaceId } },
          body: { template: { id: templateId } },
        }),
      );
      if (data) return data.workflow_id;
      const failure = new ApiError(response.status, error, "Could not open the builder");
      const existing = existingWorkflow(error);
      if (failure.code === "workflow_exists" && existing) return existing;
      throw failure;
    },
  });
}

function existingWorkflow(error: unknown): string | null {
  const detail = detailOf(error);
  if (detail && typeof detail === "object" && "workflow_id" in detail) {
    return typeof detail.workflow_id === "string" ? detail.workflow_id : null;
  }
  return null;
}
