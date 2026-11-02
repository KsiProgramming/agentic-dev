import { expect, type APIRequestContext } from "@playwright/test";

import { apiURL, e2eWorkspaceId } from "./workspace";

/** Stores `spec` as version 1 of a workflow in the E2E workspace (5.1). */
export async function createWorkflow(request: APIRequestContext, spec: object): Promise<void> {
  const created = await request.post(`${apiURL}/workflows`, {
    params: { workspace_id: e2eWorkspaceId() },
    data: { spec },
  });
  expect(created.status(), await created.text()).toBe(201);
}

/** Stores a template's workflow in the E2E workspace, or keeps the one already there. Returns
 * its id. */
export async function workflowFromTemplate(
  request: APIRequestContext,
  template: string,
): Promise<string> {
  const created = await request.post(`${apiURL}/workflows`, {
    params: { workspace_id: e2eWorkspaceId() },
    data: { template: { id: template } },
  });
  const body = (await created.json()) as {
    workflow_id?: string;
    detail?: { workflow_id?: string };
  };
  const id = body.workflow_id ?? body.detail?.workflow_id;
  expect(id, JSON.stringify(body)).toBeTruthy();
  return id!;
}

/** The latest version of a workflow, or version `version`. */
export async function getWorkflow(
  request: APIRequestContext,
  workflowId: string,
  version?: number,
): Promise<{ version: number; base_version: number | null; spec: Spec; ops: unknown[] | null }> {
  const response = await request.get(`${apiURL}/workflows/${workflowId}`, {
    params: { workspace_id: e2eWorkspaceId(), ...(version ? { version } : {}) },
  });
  expect(response.status()).toBe(200);
  return response.json();
}

export interface Spec {
  id: string;
  name: string;
  root: { type: string; id: string; steps: { id: string; type: string }[] };
}
