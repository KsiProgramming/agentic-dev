"use client";

import { BadgeCheckIcon, BoxesIcon, CircleAlertIcon, UsersIcon } from "lucide-react";
import Link from "next/link";
import { useId, useState, type FormEvent } from "react";

import { ErrorState } from "@/components/states";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { FieldMessage } from "@/forms/schema-form/schema-fields";
import { MD_UP, useMediaQuery } from "@/lib/use-media-query";
import type { WorkflowSpec } from "@/runs/graph/spec-graph";

import type { WorkflowCaller } from "./api";
import {
  blockReason,
  extractNodes,
  laterSteps,
  rangeOf,
  WRAP_CHOICES,
  wrapNodes,
  type Edit,
  type WrapKind,
} from "./edits";
import { slugify, WORKFLOW_ID } from "./new-workflow";
import type { NodeManifest } from "./node-types";
import { applyGraphOps, OpError } from "./ops";

/**
 * Composites in the builder (6.6): the dialogs that extract steps into a new workflow or wrap
 * them in a container, publishing a version, and who calls a composite. Badges are neutral, as a
 * version's state is not a run's status.
 */

/** A version that other workflows may call. */
export function PublishedBadge() {
  return (
    <Badge variant="secondary" className="h-5 px-1.5" data-testid="published-badge">
      <BadgeCheckIcon aria-hidden="true" data-icon="inline-start" />
      Published
    </Badge>
  );
}

/** A workflow with a published version: other workflows call it from their palette. */
export function CompositeBadge() {
  return (
    <Badge variant="secondary" className="h-5 px-1.5" data-testid="composite-badge">
      <BoxesIcon aria-hidden="true" data-icon="inline-start" />
      Composite
    </Badge>
  );
}

/** What the range dialog does: extract the steps into a new workflow, or wrap them in a
 * container of `kind`, starting at the step `nodeId`. */
export type RangeRequest = { nodeId: string } & (
  { mode: "extract" } | { mode: "wrap"; kind: WrapKind }
);

/** Why a wrap of `kind` from `nodeId` is not offered, for its menu item; `null` when it is. */
export function wrapReason(spec: WorkflowSpec, nodeId: string, kind: WrapKind): string | null {
  if (kind === "parallel" && laterSteps(spec, nodeId).length === 0) {
    return "A parallel needs two or more steps in a row.";
  }
  return null;
}

/** Why the edit cannot be made, as a sentence: the op's refusal, or a node it would put where
 * it cannot be or a connection whose ports would not fit; `null` when it can. */
function refusalOf(spec: WorkflowSpec, edit: Edit): string | null {
  try {
    applyGraphOps(spec, edit.ops);
  } catch (err) {
    if (err instanceof OpError) return err.message;
    throw err;
  }
  return blockReason(spec, edit);
}

interface RangeDialogProps {
  request: RangeRequest | null;
  spec: WorkflowSpec;
  manifests: NodeManifest[];
  /** The ids of the workspace's workflows, and those unsaved extracts will make. */
  takenIds: Set<string>;
  onCancel: () => void;
  onApply: (edit: Edit) => void;
}

/** Extract steps to a composite, or wrap them in a container (6.6): the range from the step the
 * menu was opened on through a later step of its sequence, and for an extract the new
 * workflow's name, id and description. The edit is checked as it is made, with the reason shown
 * when it cannot be. */
export function RangeDialog(props: RangeDialogProps) {
  const { request, onCancel } = props;
  return (
    <Dialog open={request !== null} onOpenChange={(open) => (open ? null : onCancel())}>
      <DialogContent className="sm:max-w-lg">
        {/* Keyed, so a new request starts with a fresh form. */}
        {request ? (
          <RangeForm key={`${request.mode}:${request.nodeId}`} {...props} request={request} />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function RangeForm({
  request,
  spec,
  manifests,
  takenIds,
  onCancel,
  onApply,
}: RangeDialogProps & { request: RangeRequest }) {
  const throughId = useId();
  const nameId = useId();
  const idId = useId();
  const descriptionId = useId();
  const later = laterSteps(spec, request.nodeId);
  const wrapKind = request.mode === "wrap" ? request.kind : null;
  // A parallel needs two branches, so its range starts at two steps.
  const [through, setThrough] = useState<string | null>(
    wrapKind === "parallel" ? (later[0] ?? null) : null,
  );
  const [name, setName] = useState("");
  const [ownId, setOwnId] = useState<string | null>(null);
  const [description, setDescription] = useState("");
  const [errors, setErrors] = useState<{ name?: string; id?: string }>({});

  const nodeIds = rangeOf(spec, request.nodeId, through);
  const workflowId = ownId ?? (name.trim() ? slugify(name) : "");
  const edit =
    request.mode === "wrap"
      ? wrapNodes(spec, nodeIds, request.kind, manifests)
      : extractNodes(spec, nodeIds, {
          id: workflowId || "workflow",
          name: name.trim() || "Workflow",
          description: description.trim() || undefined,
        });
  const refusal = refusalOf(spec, edit);
  const kindLabel = WRAP_CHOICES.find((c) => c.kind === wrapKind)?.label.toLowerCase();
  const title =
    request.mode === "extract" ? "Extract to a composite" : `Wrap in a ${kindLabel ?? "container"}`;

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (refusal) return;
    if (request.mode === "extract") {
      const found: { name?: string; id?: string } = {};
      if (!name.trim()) found.name = "Give the composite a name.";
      if (!WORKFLOW_ID.test(workflowId)) {
        found.id = "Use lower-case letters, digits, - and _, starting with a letter.";
      } else if (takenIds.has(workflowId) || workflowId === spec.id) {
        found.id = "A workflow with this id exists; choose another.";
      }
      setErrors(found);
      if (Object.keys(found).length > 0) return;
    }
    onApply(edit);
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>
          {request.mode === "extract"
            ? "The steps move into a new workflow, called here in their place. Publish it to reuse it in other workflows."
            : "The steps move into a new container, in their place."}{" "}
          Undo brings them back until you save.
        </DialogDescription>
      </DialogHeader>
      <Field>
        <FieldLabel htmlFor={throughId}>Steps</FieldLabel>
        {later.length > 0 ? (
          <NativeSelect
            id={throughId}
            className="w-full"
            value={through ?? ""}
            aria-describedby={refusal ? `${throughId}-refusal` : undefined}
            onChange={(e) => setThrough(e.target.value === "" ? null : e.target.value)}
          >
            {wrapKind === "parallel" ? null : (
              <NativeSelectOption value="">Only {request.nodeId}</NativeSelectOption>
            )}
            {later.map((id) => (
              <NativeSelectOption key={id} value={id}>
                {request.nodeId} through {id}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        ) : (
          <p id={throughId} className="font-mono text-meta text-foreground">
            {request.nodeId}
          </p>
        )}
        {refusal ? (
          <p
            id={`${throughId}-refusal`}
            role="status"
            className="flex items-start gap-1 text-meta text-status-failed"
          >
            <CircleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            <span>{refusal}</span>
          </p>
        ) : (
          <FieldDescription>
            {nodeIds.length === 1 ? "1 step" : `${nodeIds.length} steps`}:{" "}
            <span className="font-mono">{nodeIds.join(", ")}</span>
          </FieldDescription>
        )}
      </Field>
      {request.mode === "extract" ? (
        <>
          <Field data-invalid={errors.name ? true : undefined}>
            <FieldLabel htmlFor={nameId}>Name</FieldLabel>
            <Input
              id={nameId}
              value={name}
              autoComplete="off"
              placeholder="Security review"
              aria-invalid={errors.name ? true : undefined}
              aria-describedby={errors.name ? `${nameId}-error` : undefined}
              onChange={(e) => setName(e.target.value)}
            />
            {errors.name ? <FieldMessage id={`${nameId}-error`}>{errors.name}</FieldMessage> : null}
          </Field>
          <Field data-invalid={errors.id ? true : undefined}>
            <FieldLabel htmlFor={idId}>Id</FieldLabel>
            <Input
              id={idId}
              value={workflowId}
              autoComplete="off"
              spellCheck={false}
              className="font-mono"
              placeholder="security-review"
              aria-invalid={errors.id ? true : undefined}
              aria-describedby={errors.id ? `${idId}-error` : `${idId}-help`}
              onChange={(e) => setOwnId(e.target.value)}
            />
            {errors.id ? (
              <FieldMessage id={`${idId}-error`}>{errors.id}</FieldMessage>
            ) : (
              <FieldDescription id={`${idId}-help`}>
                The new workflow&apos;s id. Lower-case letters, digits, - and _.
              </FieldDescription>
            )}
          </Field>
          <Field>
            <FieldLabel htmlFor={descriptionId}>Description (optional)</FieldLabel>
            <Textarea
              id={descriptionId}
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
        </>
      ) : null}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={refusal !== null}>
          {request.mode === "extract" ? "Extract" : "Wrap"}
        </Button>
      </DialogFooter>
    </form>
  );
}

/** The callers of a composite as loaded: rows, or why they could not be. */
export interface Callers {
  data: WorkflowCaller[] | undefined;
  error: string | null;
  retry: () => void;
}

/** Publish version `version`: who calls the composite keeps the version it calls. */
export function PublishDialog({
  open,
  version,
  callers,
  error,
  pending,
  onOpenChange,
  onPublish,
}: {
  open: boolean;
  version: number;
  callers: Callers;
  error: string | null;
  pending: boolean;
  onOpenChange: (open: boolean) => void;
  onPublish: () => void;
}) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Publish version {version}?</AlertDialogTitle>
          <AlertDialogDescription>
            Other workflows can then add it from their palette, under Workspace nodes. A published
            version never changes; later versions stay drafts until you publish them.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <CallerList callers={callers} intro="Workflows that call it keep the version they call:" />
        {error ? (
          <p role="alert" className="flex items-start gap-1 text-meta text-status-failed">
            <CircleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            <span>{error}</span>
          </p>
        ) : null}
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            disabled={pending}
            onClick={(event) => {
              event.preventDefault();
              onPublish();
            }}
          >
            {pending ? "Publishing…" : "Publish"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

/** Each workflow that calls the composite, a link to it, with the version it calls. Nothing
 * when none does (the publish dialog) unless `empty` says so (Used by). */
function CallerList({
  callers,
  intro,
  empty,
}: {
  callers: Callers;
  intro?: string;
  empty?: string;
}) {
  if (callers.error) {
    return <ErrorState message={callers.error} onRetry={callers.retry} />;
  }
  if (!callers.data) {
    return (
      <div className="flex flex-col gap-2" aria-label="Loading who calls it">
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-4 w-1/2" />
      </div>
    );
  }
  if (callers.data.length === 0) {
    return empty ? <p className="text-meta text-foreground-secondary">{empty}</p> : null;
  }
  return (
    <div className="flex flex-col gap-2 text-meta">
      {intro ? <p className="text-foreground-secondary">{intro}</p> : null}
      <ul className="flex flex-col gap-1" data-testid="caller-list">
        {callers.data.map((c) => (
          <li key={c.workflow_id} className="flex min-w-0 items-baseline justify-between gap-3">
            <Link
              href={`/workflows/${encodeURIComponent(c.workflow_id)}`}
              className="min-w-0 truncate font-medium text-foreground underline-offset-2 hover:underline"
            >
              {c.name}
            </Link>
            <span className="shrink-0 text-foreground-secondary">
              calls version {c.calls_version}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** "Used by N workflows" in the builder's status line, a composite's callers in a popover (a
 * bottom sheet below 768 px). */
export function CallersStatus({ callers }: { callers: Callers }) {
  const md = useMediaQuery(MD_UP);
  const [open, setOpen] = useState(false);
  const n = callers.data?.length;
  const label =
    callers.error !== null
      ? "Used by: could not load"
      : n === undefined
        ? "Used by…"
        : n === 0
          ? "Used by no workflow yet"
          : `Used by ${n} ${n === 1 ? "workflow" : "workflows"}`;
  const trigger = (
    <button
      type="button"
      onClick={() => setOpen(true)}
      className="flex items-center gap-1 rounded-sm underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
    >
      <UsersIcon aria-hidden="true" className="size-3.5 shrink-0" />
      {label}
    </button>
  );
  const list = <CallerList callers={callers} empty="No workflow calls this one yet." />;
  if (md) {
    return (
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>{trigger}</PopoverTrigger>
        <PopoverContent align="start" className="w-80 max-w-[calc(100vw-2rem)]">
          <p className="mb-2 text-caption font-medium text-muted-foreground">Used by</p>
          {list}
        </PopoverContent>
      </Popover>
    );
  }
  return (
    <>
      {trigger}
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="bottom" className="max-h-[80svh] gap-0 p-0">
          <SheetHeader className="border-b">
            <SheetTitle>Used by</SheetTitle>
            <SheetDescription>The workflows whose latest version calls this one.</SheetDescription>
          </SheetHeader>
          <div className="overflow-y-auto p-4">{list}</div>
        </SheetContent>
      </Sheet>
    </>
  );
}
