"use client";

import type { UiSchema } from "@rjsf/utils";
import { LoaderCircleIcon, PlayIcon, SkipForwardIcon, SlidersHorizontalIcon } from "lucide-react";
import Link from "next/link";
import { useId, useState } from "react";

import { IdChip } from "@/components/display";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Field, FieldContent, FieldDescription, FieldLabel } from "@/components/ui/field";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useWorkspaceId } from "@/workspace";
import { useNodeTypes } from "@/workflows/node-types";
import { nodeParams, paramOps, type Schema } from "@/workflows/params";
import { ParamForm } from "@/workflows/side-panel";

import type { SpecNode, WorkflowSpec } from "../graph/spec-graph";
import { topLevelSteps } from "../graph/spec-graph";
import { useRerun, type RerunFrom } from "../rerun";
import { useRunChanges } from "../use-run-changes";

type Json = Record<string, unknown>;

/** Whether `nodeId` is a top-level step of `spec`, which a run can be rerun from (12.4). */
export function isTopLevelStep(spec: WorkflowSpec | null, nodeId: string): boolean {
  return spec !== null && topLevelSteps(spec).some((step) => step.id === nodeId);
}

/** The `from` of a rerun from `node`: its id, the parameters changed from `before` to `after`
 * (`setParam` paths and values, on that node only), and whether it starts from its uncommitted
 * work. */
export function rerunFrom(
  node: SpecNode,
  before: Json,
  after: Json,
  schema: Schema,
  useWip: boolean,
): RerunFrom {
  const set_params = paramOps(node.id, before, after, schema).flatMap((op) =>
    op.op === "setParam" ? [{ path: op.path, value: op.value as RerunFrom["set_params"] }] : [],
  ) as NonNullable<RerunFrom["set_params"]>;
  return { node_id: node.id, set_params, use_wip: useWip };
}

/**
 * "Rerun from here" on a top-level step of an ended run (12.4): a sheet with the step's
 * parameters, as the builder's panel draws them, to change before a new run starts from that
 * step; the steps before it are not run or charged again, and its code is restored as it was
 * before it. `wipAvailable` offers to start from the work the step left uncommitted.
 */
export function RerunFromStepButton({
  runId,
  node,
  wipAvailable,
  baseUrl,
}: {
  runId: string;
  node: SpecNode;
  wipAvailable: boolean;
  baseUrl?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button type="button" size="sm" variant="outline" onClick={() => setOpen(true)}>
        <SkipForwardIcon aria-hidden="true" data-icon="inline-start" />
        Rerun from here
      </Button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent className="w-full gap-0 sm:max-w-xl" aria-describedby={undefined}>
          {open ? (
            <RerunFromStepForm
              runId={runId}
              node={node}
              wipAvailable={wipAvailable}
              baseUrl={baseUrl}
              onCancel={() => setOpen(false)}
            />
          ) : null}
        </SheetContent>
      </Sheet>
    </>
  );
}

function RerunFromStepForm({
  runId,
  node,
  wipAvailable,
  baseUrl,
  onCancel,
}: {
  runId: string;
  node: SpecNode;
  wipAvailable: boolean;
  baseUrl?: string;
  onCancel: () => void;
}) {
  const workspaceId = useWorkspaceId();
  const types = useNodeTypes(baseUrl, workspaceId);
  const rerun = useRerun({ baseUrl });
  const manifest = types.data?.find((m) => m.kind === node.type);
  const before = nodeParams(node, manifest);
  const [after, setAfter] = useState<Json>(before);
  const [useWip, setUseWip] = useState(false);
  const formId = useId();
  const wipId = useId();
  const schema = (manifest?.parameters ?? {}) as Schema;

  let body: React.ReactNode;
  if (types.isPending) body = <LoadingState label="Loading the step's parameters…" />;
  else if (types.isError) {
    body = <ErrorState message={types.error.message} onRetry={() => types.refetch()} />;
  } else if (!manifest) {
    body = (
      <EmptyState
        icon={SlidersHorizontalIcon}
        message="This step has no parameters to change; it runs again as it is."
      />
    );
  } else {
    body = (
      <ParamForm
        idPrefix={`rerun-${node.id}`}
        schema={schema}
        ui={(manifest.ui ?? {}) as UiSchema}
        values={before}
        onChange={setAfter}
      />
    );
  }

  return (
    <form
      id={formId}
      className="flex min-h-0 flex-1 flex-col"
      onSubmit={(event) => {
        event.preventDefault();
        rerun.mutate({ runId, from: rerunFrom(node, before, after, schema, useWip) });
      }}
    >
      <SheetHeader>
        <SheetTitle>
          Rerun from <span className="font-mono">{node.id}</span>
        </SheetTitle>
        <SheetDescription>
          The steps before it are not run again, and its code is restored as it was before it.
        </SheetDescription>
      </SheetHeader>
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 pb-4">
        {wipAvailable ? (
          <Field orientation="horizontal">
            <Checkbox
              id={wipId}
              checked={useWip}
              onCheckedChange={(checked) => setUseWip(checked === true)}
            />
            <FieldContent>
              <FieldLabel htmlFor={wipId}>Start from its uncommitted work</FieldLabel>
              <FieldDescription>
                The edits this step had not committed when the run ended, as one commit.
              </FieldDescription>
            </FieldContent>
          </Field>
        ) : null}
        {body}
      </div>
      <SheetFooter className="flex-row justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={rerun.isPending || types.isPending}>
          {rerun.isPending ? (
            <LoaderCircleIcon
              aria-hidden="true"
              data-icon="inline-start"
              className="motion-safe:animate-spin"
            />
          ) : (
            <PlayIcon aria-hidden="true" data-icon="inline-start" />
          )}
          {rerun.isPending ? "Starting…" : "Start rerun"}
        </Button>
      </SheetFooter>
    </form>
  );
}

/** The steps a rerun from a step did not run again (12.4), from its `run_started`: each links
 * to that step in the run it came from, where its output and cost are. */
export function CarriedSteps({ from, steps }: { from: string; steps: string[] }) {
  if (steps.length === 0) return null;
  return (
    <p data-testid="carried-steps" className="px-2 pb-2 text-meta text-foreground-secondary">
      Carried over from <RerunSource runId={from} />, not run again:{" "}
      {steps.map((step, index) => (
        <span key={step}>
          {index > 0 ? ", " : null}
          <Link
            href={`/runs/${from}?step=${encodeURIComponent(step)}`}
            className="font-mono underline-offset-2 hover:underline"
          >
            {step}
          </Link>
        </span>
      ))}
    </p>
  );
}

function RerunSource({ runId }: { runId: string }) {
  return <IdChip id={runId} label="run" href={`/runs/${runId}`} />;
}

/** The steps a rerun from a step carried over, from its `run_started` event. */
export function carriedSteps(events: readonly { type: string; payload?: unknown }[]): string[] {
  const started = events.find((e) => e.type === "run_started");
  const carried = (started?.payload as { carried?: unknown } | undefined)?.carried;
  return Array.isArray(carried) ? carried.filter((s): s is string => typeof s === "string") : [];
}

/**
 * The selected step's "Rerun from here", for an ended run (12.4): only on a top-level step.
 * `endedHere` says the run ended in this step, which may have left uncommitted work to start
 * from; whether it did is read from what the run saved.
 */
export function StepRerunAction({
  runId,
  spec,
  nodeId,
  endedHere,
  baseUrl,
}: {
  runId: string;
  spec: WorkflowSpec | null;
  nodeId: string;
  endedHere: boolean;
  baseUrl?: string;
}) {
  const node = spec ? topLevelSteps(spec).find((step) => step.id === nodeId) : undefined;
  const changes = useRunChanges(runId, { enabled: node !== undefined && endedHere, baseUrl });
  if (!node) return null;
  const wipAvailable = endedHere && (changes.data ?? []).some((b) => b.kind === "wip");
  return (
    <RerunFromStepButton runId={runId} node={node} wipAvailable={wipAvailable} baseUrl={baseUrl} />
  );
}

/** The last top-level step the run started, of `stepIds` in the order it ran them: the step an
 * ended run ended in. */
export function lastTopLevelStep(spec: WorkflowSpec | null, stepIds: string[]): string | null {
  if (!spec) return null;
  const tops = new Set(topLevelSteps(spec).map((step) => step.id));
  return [...stepIds].reverse().find((id) => tops.has(id)) ?? null;
}
