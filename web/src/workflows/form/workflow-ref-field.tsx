"use client";

import type { FieldProps } from "@rjsf/utils";
import { ExternalLinkIcon } from "lucide-react";
import Link from "next/link";
import { useId } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";

import { useWorkflows, useWorkflowVersions } from "../api";

/** What the side panel's form knows about where it is: the workspace, and the workflow being
 * edited (which a subflow may not call). */
export interface BuilderFormContext {
  workspaceId: string;
  workflowId: string;
}

interface WorkflowRef {
  id: string;
  version: number;
}

function isRef(value: unknown): value is WorkflowRef {
  if (typeof value !== "object" || value === null) return false;
  const { id, version } = value as Record<string, unknown>;
  return typeof id === "string" && typeof version === "number";
}

/**
 * A subflow's `workflow` (6.5, `ui:field: workflow_ref`): a stored workflow of the workspace,
 * then one of its versions (the latest when a workflow is picked), and a link to open it. The
 * workflow being edited is left out: a workflow may not call itself. Deeper cycles are the live
 * check's (`subflow_cycle`).
 */
export function WorkflowRefField(props: FieldProps) {
  const { formData, onChange, fieldPathId, disabled, readonly, rawErrors, registry } = props;
  const context = registry.formContext as Partial<BuilderFormContext> | undefined;
  const workspaceId = context?.workspaceId ?? "";
  const editing = context?.workflowId ?? null;
  const value = isRef(formData) ? formData : null;
  const workflows = useWorkflows(workspaceId, Boolean(workspaceId));
  const versions = useWorkflowVersions(workspaceId, value?.id ?? "", Boolean(value?.id));
  const workflowId = useId();
  const versionId = useId();
  const locked = disabled || readonly;
  const others = (workflows.data ?? []).filter((w) => w.workflow_id !== editing);
  const known = others.some((w) => w.workflow_id === value?.id);

  const pick = (id: string) => {
    const found = others.find((w) => w.workflow_id === id);
    if (found) onChange({ id, version: found.latest_version }, fieldPathId.path);
  };

  let workflowControl: React.ReactNode;
  if (workflows.isPending) {
    workflowControl = <p className="text-meta text-muted-foreground">Loading workflows…</p>;
  } else if (workflows.isError) {
    workflowControl = (
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-meta text-destructive">Could not load the workflows.</p>
        <Button type="button" size="sm" variant="outline" onClick={() => void workflows.refetch()}>
          Retry
        </Button>
      </div>
    );
  } else if (others.length === 0 && !value) {
    workflowControl = (
      <p className="text-meta text-muted-foreground">
        No other workflows yet. Create one, then call it here.
      </p>
    );
  } else {
    workflowControl = (
      <NativeSelect
        id={workflowId}
        className="w-full"
        value={value?.id ?? ""}
        disabled={locked}
        aria-invalid={rawErrors?.length ? true : undefined}
        onChange={(e) => pick(e.target.value)}
      >
        <NativeSelectOption value="" disabled>
          Pick a workflow
        </NativeSelectOption>
        {value && !known ? (
          // A workflow this workspace does not have (or this one): the live check says so.
          <NativeSelectOption value={value.id}>{value.id}</NativeSelectOption>
        ) : null}
        {others.map((w) => (
          <NativeSelectOption key={w.workflow_id} value={w.workflow_id}>
            {w.name} ({w.workflow_id})
          </NativeSelectOption>
        ))}
      </NativeSelect>
    );
  }

  const listed = versions.data ?? [];
  const latest = listed[0]?.version ?? null;
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="flex min-w-0 flex-col gap-1.5">
        <Label htmlFor={workflowId}>Workflow</Label>
        {workflowControl}
      </div>
      {value ? (
        <div className="flex min-w-0 flex-col gap-1.5">
          <Label htmlFor={versionId}>Version</Label>
          <NativeSelect
            id={versionId}
            className="w-full"
            value={String(value.version)}
            disabled={locked || versions.isPending}
            onChange={(e) =>
              onChange({ id: value.id, version: Number(e.target.value) }, fieldPathId.path)
            }
          >
            {listed.some((v) => v.version === value.version) ? null : (
              <NativeSelectOption value={String(value.version)}>
                Version {value.version}
              </NativeSelectOption>
            )}
            {listed.map((v) => (
              <NativeSelectOption key={v.version} value={String(v.version)}>
                Version {v.version}
                {v.version === latest ? " (latest)" : ""}
              </NativeSelectOption>
            ))}
          </NativeSelect>
          {latest !== null && value.version < latest ? (
            <p className="text-caption text-muted-foreground">
              Version {latest} is the latest. A call runs the version it names.
            </p>
          ) : null}
          <Link
            href={`/workflows/${encodeURIComponent(value.id)}?version=${value.version}`}
            className="inline-flex w-fit items-center gap-1 rounded-sm text-meta text-foreground-secondary underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
          >
            Open workflow
            <ExternalLinkIcon aria-hidden="true" className="size-3.5" />
          </Link>
        </div>
      ) : null}
      {rawErrors?.length ? (
        <p className="text-caption text-destructive">{rawErrors.join(" ")}</p>
      ) : null}
    </div>
  );
}
