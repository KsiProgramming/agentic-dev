"use client";

import {
  CircleAlertIcon,
  EllipsisIcon,
  PencilIcon,
  PlusIcon,
  ReplaceIcon,
  RotateCwIcon,
  SlidersHorizontalIcon,
  Undo2Icon,
  WorkflowIcon,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";

import { ApiError, detailOf } from "@/api/errors";
import { PageHeader } from "@/components/page-header";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
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
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { LG_UP, useMediaQuery } from "@/lib/use-media-query";
import { cn } from "@/lib/utils";
import { isKnownKind, KindIcon, kindLabel } from "@/runs/graph/node-kinds";
import {
  allSpecNodes,
  type NodeKind,
  type SpecNode,
  type WorkflowSpec,
} from "@/runs/graph/spec-graph";
import { CARD, SpecTree, type MapNode } from "@/runs/graph/spec-tree";
import { useWorkspaceId } from "@/workspace";

import { useSaveWorkflow, useWorkflow, type WorkflowVersion } from "./api";
import {
  addBranch,
  addStep,
  moveStep,
  moveTargets,
  moveTo,
  placeOf,
  removeStep,
  replaceNode,
  stayReason,
  subtreeSize,
  type Edit,
  type MoveTarget,
} from "./edits";
import { ManifestIcon, paletteGroups, useNodeTypes, type NodeManifest } from "./node-types";
import { applyOps, OpError } from "./ops";
import { NodePanel, WorkflowPanel } from "./side-panel";

/** A refusal shown on the card of the node it is about, until the edits change. */
interface Refusal {
  nodeId: string | null;
  message: string;
}

/**
 * The builder (5.2): a stored workflow drawn as the run map's cards, edited through each node's
 * menu, at any depth (5.5), and the side panel (5.4), where the selected node's parameters, or the workflow's
 * own fields, are edited. Edits are graph operations kept here until Save sends them as one
 * `PATCH /workflows/{id}`; what is drawn is the stored version with them applied.
 */
export function WorkflowBuilder({ workflowId }: { workflowId: string }) {
  const workspaceId = useWorkspaceId();
  const query = useWorkflow(workspaceId, workflowId);

  if (query.isPending) return <LoadingState label="Loading workflow…" />;
  if (query.isError) {
    return <ErrorState message={query.error.message} onRetry={() => void query.refetch()} />;
  }
  if (!query.data) {
    return (
      <EmptyState
        icon={WorkflowIcon}
        message="There is no workflow with this id."
        description="Open one from a template to edit it here."
        action={
          <Button asChild variant="outline">
            <Link href="/templates">Go to templates</Link>
          </Button>
        }
      />
    );
  }
  return (
    <Editor
      key={query.data.workflow_id}
      version={query.data}
      workspaceId={workspaceId}
      refetch={async () => (await query.refetch()).data ?? null}
    />
  );
}

function Editor({
  version,
  workspaceId,
  refetch,
}: {
  version: WorkflowVersion;
  workspaceId: string;
  refetch: () => Promise<WorkflowVersion | null>;
}) {
  const [edits, setEdits] = useState<Edit[]>([]);
  const [refusal, setRefusal] = useState<Refusal | null>(null);
  const [removing, setRemoving] = useState<Removal | null>(null);
  // The card to focus once an edit drew it: menus close, and a replaced node's card is gone.
  const focusNext = useRef<string | null>(null);
  const [discarding, setDiscarding] = useState(false);
  // The node whose parameters the panel shows; none: the workflow's own fields. A node that is
  // gone (removed, undone) is no longer selected. Below 1024 px the panel is a sheet.
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const wide = useMediaQuery(LG_UP);
  const save = useSaveWorkflow(workspaceId, version.workflow_id);
  const nodeTypes = useNodeTypes();
  const manifests = useMemo(() => nodeTypes.data ?? [], [nodeTypes.data]);
  const palette: Palette = {
    groups: paletteGroups(manifests),
    pending: nodeTypes.isPending,
    error: nodeTypes.isError ? nodeTypes.error.message : null,
    retry: () => void nodeTypes.refetch(),
  };
  const manifestOf = (kind: string) => manifests.find((m) => m.kind === kind);

  const ops = useMemo(() => edits.flatMap((e) => e.ops), [edits]);
  const base = version.spec as unknown as WorkflowSpec;
  // Each edit was checked before it was kept. On a newer base (after a conflict) they may no
  // longer apply until `rebase` drops them: the base is drawn meanwhile.
  const spec = useMemo(() => {
    try {
      return applyOps(base, ops);
    } catch {
      return base;
    }
  }, [base, ops]);
  const dirty = edits.length > 0;
  const selected = selectedId
    ? (allSpecNodes(spec).find((n) => n.id === selectedId) ?? null)
    : null;

  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  useEffect(() => {
    const id = focusNext.current;
    if (!id) return;
    focusNext.current = null;
    // After the menu has given the focus back to its trigger.
    const timer = setTimeout(() =>
      document.querySelector<HTMLElement>(`[data-select="${CSS.escape(id)}"]`)?.focus(),
    );
    return () => clearTimeout(timer);
  }, [spec]);

  function apply(edit: Edit | null) {
    if (!edit) return;
    try {
      applyOps(base, [...ops, ...edit.ops]);
    } catch (err) {
      if (!(err instanceof OpError)) throw err;
      setRefusal({ nodeId: err.node_id, message: err.message });
      toast.error(err.message);
      return;
    }
    setRefusal(null);
    focusNext.current = edit.focus ?? null;
    // Typing in one field of the panel is one undo step: the newer edit replaces the last.
    setEdits((current) =>
      edit.key && current.at(-1)?.key === edit.key
        ? [...current.slice(0, -1), edit]
        : [...current, edit],
    );
  }

  function select(nodeId: string | null) {
    setSelectedId(nodeId);
    setSheetOpen(true);
  }

  /** Close the panel and give the focus back to the card it was about. */
  function closePanel() {
    const id = selectedId;
    setSelectedId(null);
    setSheetOpen(false);
    if (id) {
      requestAnimationFrame(() =>
        document.querySelector<HTMLElement>(`[data-select="${CSS.escape(id)}"]`)?.focus(),
      );
    }
  }

  function undo() {
    setRefusal(null);
    setEdits((current) => current.slice(0, -1));
  }

  async function onSave() {
    try {
      const saved = await save.mutateAsync({ baseVersion: version.version, ops });
      setEdits([]);
      setRefusal(null);
      toast.success(`Saved version ${saved.version}`);
    } catch (err) {
      if (err instanceof ApiError && err.code === "version_conflict") {
        await rebase();
        return;
      }
      const message = err instanceof Error ? err.message : String(err);
      setRefusal({ nodeId: opErrorNode(err), message });
      toast.error(message);
    }
  }

  /** Someone saved a newer version: take it, and keep the edits if they still apply to it. */
  async function rebase() {
    const latest = await refetch();
    if (!latest) {
      toast.error("The workflow could not be reloaded.");
      return;
    }
    try {
      applyOps(latest.spec, ops);
      toast.info(`Updated to version ${latest.version}; your edits were kept. Save again.`);
    } catch (err) {
      setEdits([]);
      const reason = err instanceof Error ? err.message : String(err);
      toast.error(`Updated to version ${latest.version}; your edits were dropped: ${reason}`);
    }
  }

  function renderCard(node: MapNode): ReactNode {
    // Every node is edited where it is; a route's card is not a node.
    const place = node.kind === "route" ? null : placeOf(spec, node.id);
    const failed = refusal?.nodeId === node.id ? refusal.message : null;
    const isSelected = selected?.id === node.id;
    const kind = node.kind === "route" ? null : (node.kind as NodeKind);
    // A kind the web has no icon or name for is drawn from its manifest (5.3).
    const manifest = kind ? manifestOf(kind) : undefined;
    const known = kind !== null && isKnownKind(kind);
    return (
      <div
        data-testid="builder-node"
        data-node={node.id}
        className={cn(
          CARD,
          node.kind === "route" && "border-dashed bg-surface-subtle",
          failed && "border-status-failed-border",
          isSelected && "ring-2 ring-primary",
        )}
      >
        <span className="flex min-w-0 items-center gap-2">
          {kind ? (
            <button
              type="button"
              data-select={node.id}
              aria-pressed={isSelected}
              aria-label={`Edit parameters of ${node.name}`}
              onClick={() => select(node.id)}
              className="min-w-0 truncate rounded-sm text-left font-mono text-meta font-medium outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
            >
              {node.name}
            </button>
          ) : (
            <span className="truncate font-mono text-meta font-medium">{node.name}</span>
          )}
          {kind && known ? (
            <KindIcon kind={kind} className="ml-auto size-3.5 shrink-0 text-muted-foreground" />
          ) : kind ? (
            <ManifestIcon
              name={manifest?.icon ?? ""}
              className="ml-auto size-3.5 shrink-0 text-muted-foreground"
            />
          ) : null}
          {place ? (
            <StepMenu
              node={place.node}
              canMoveUp={moveStep(spec, node.id, "up") !== null}
              canMoveDown={moveStep(spec, node.id, "down") !== null}
              stayReason={stayReason(place)}
              canReplace={place.parent !== null}
              targets={moveTargets(spec, node.id)}
              palette={palette}
              onEditParams={() => select(node.id)}
              onAdd={(k) => apply(addStep(spec, node.id, k, manifests))}
              onAddBranch={(k) => apply(addBranch(spec, node.id, k, manifests))}
              onMove={(d) => apply(moveStep(spec, node.id, d))}
              onMoveTo={(target) => apply(moveTo(spec, node.id, target))}
              onReplace={(k) => setRemoving({ node: place.node, replaceWith: k })}
              onRemove={(n) => setRemoving({ node: n })}
            />
          ) : null}
        </span>
        {failed ? (
          <span className="flex min-w-0 items-center gap-1 text-caption text-status-failed">
            <CircleAlertIcon aria-hidden="true" className="size-3 shrink-0" />
            <span className="truncate" title={failed}>
              {failed}
            </span>
          </span>
        ) : (
          <span className="truncate text-caption text-foreground-secondary">
            {node.kind === "route"
              ? "Route"
              : node.detail || (known ? kindLabel(node.kind) : (manifest?.label ?? node.kind))}
          </span>
        )}
      </div>
    );
  }

  function panel(onClose: (() => void) | undefined): ReactNode {
    if (!selected) return <WorkflowPanel spec={spec} onEdit={apply} onClose={onClose} />;
    return (
      <NodePanel
        node={selected}
        manifests={manifests}
        pending={nodeTypes.isPending}
        error={nodeTypes.isError ? nodeTypes.error.message : null}
        retry={() => void nodeTypes.refetch()}
        refusal={refusal?.nodeId === selected.id ? refusal.message : null}
        onEdit={apply}
        onClose={onClose}
      />
    );
  }

  const issues = version.issues.length;
  return (
    <>
      <PageHeader
        title={spec.name}
        aside={
          <span className="font-mono text-caption text-foreground-secondary">
            {version.workflow_id}
          </span>
        }
        description={spec.description ?? "No description."}
        actions={
          <>
            <Button type="button" variant="ghost" onClick={() => select(null)}>
              <PencilIcon aria-hidden="true" data-icon="inline-start" />
              Edit details
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={!dirty || save.isPending}
              onClick={undo}
              aria-label={dirty ? `Undo: ${edits[edits.length - 1].label}` : "Undo"}
            >
              <Undo2Icon aria-hidden="true" data-icon="inline-start" />
              Undo
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={!dirty || save.isPending}
              onClick={() => setDiscarding(true)}
            >
              Discard
            </Button>
            <Button type="button" disabled={!dirty || save.isPending} onClick={() => void onSave()}>
              {save.isPending ? "Saving…" : "Save"}
            </Button>
          </>
        }
      />
      <p
        data-testid="builder-status"
        className="flex flex-wrap gap-x-3 gap-y-1 text-meta text-foreground-secondary"
      >
        <span>Version {version.version}</span>
        <span>
          {issues === 0
            ? "Ready to run"
            : `${issues} ${issues === 1 ? "issue" : "issues"} · runs refuse it until they are fixed`}
        </span>
        {dirty ? (
          <span className="font-medium text-foreground">
            {edits.length} unsaved {edits.length === 1 ? "change" : "changes"}
          </span>
        ) : null}
      </p>
      <div className="grid min-w-0 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <section
          aria-label="Workflow canvas"
          className="flex min-w-0 flex-col overflow-hidden rounded-lg border bg-background"
        >
          <div className="flex items-center justify-between gap-2 border-b bg-surface-subtle px-4 py-2">
            <h2 className="text-caption font-medium text-muted-foreground">Steps</h2>
            {spec.root.type === "sequence" ? (
              <AddMenu
                label="Add first step"
                palette={palette}
                onAdd={(k) => apply(addStep(spec, null, k, manifests))}
              />
            ) : null}
          </div>
          <div className="@container overflow-auto p-4" data-testid="builder-canvas">
            <SpecTree spec={spec} renderCard={renderCard} />
          </div>
        </section>
        {wide ? (
          <aside
            aria-label="Parameters"
            className="sticky top-4 flex max-h-[calc(100svh-2rem)] min-w-0 flex-col overflow-hidden rounded-lg border bg-background"
            onKeyDown={(event) => {
              if (event.key === "Escape" && selected) {
                event.stopPropagation();
                closePanel();
              }
            }}
          >
            {panel(selected ? closePanel : undefined)}
          </aside>
        ) : null}
      </div>
      {wide ? null : (
        <Sheet open={sheetOpen} onOpenChange={(open) => (open ? null : closePanel())}>
          <SheetContent side="right" size="md" showCloseButton={false} className="gap-0 p-0">
            <SheetTitle className="sr-only">
              {selected ? `Parameters of ${selected.id}` : "Workflow"}
            </SheetTitle>
            <SheetDescription className="sr-only">
              Changes are kept as unsaved edits until you save.
            </SheetDescription>
            {panel(closePanel)}
          </SheetContent>
        </Sheet>
      )}

      <RemoveDialog
        removal={removing}
        onCancel={() => setRemoving(null)}
        onConfirm={({ node, replaceWith }) => {
          setRemoving(null);
          apply(
            replaceWith ? replaceNode(spec, node.id, replaceWith, manifests) : removeStep(node.id),
          );
        }}
      />
      <AlertDialog open={discarding} onOpenChange={setDiscarding}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Discard unsaved changes?</AlertDialogTitle>
            <AlertDialogDescription>
              The workflow goes back to version {version.version}.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep editing</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                setEdits([]);
                setRefusal(null);
              }}
            >
              Discard
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

/** The node a `422` op error names, if the error is one. */
function opErrorNode(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  const detail = detailOf(err.body);
  if (detail && typeof detail === "object" && "node_id" in detail) {
    return typeof detail.node_id === "string" ? detail.node_id : null;
  }
  return null;
}

/** The palette: the node types from `GET /node-types`, by category. */
interface Palette {
  groups: { label: string; items: NodeManifest[] }[];
  pending: boolean;
  error: string | null;
  retry: () => void;
}

function AddItems({ palette, onAdd }: { palette: Palette; onAdd: (kind: string) => void }) {
  if (palette.pending) {
    return <DropdownMenuItem disabled>Loading node types…</DropdownMenuItem>;
  }
  if (palette.error) {
    return (
      <>
        <DropdownMenuItem disabled className="text-status-failed">
          <CircleAlertIcon aria-hidden="true" />
          {palette.error}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={palette.retry}>
          <RotateCwIcon aria-hidden="true" />
          Retry
        </DropdownMenuItem>
      </>
    );
  }
  if (palette.groups.length === 0) {
    return <DropdownMenuItem disabled>No node types available</DropdownMenuItem>;
  }
  return palette.groups.map((group, i) => (
    <DropdownMenuGroup key={group.label}>
      {i > 0 ? <DropdownMenuSeparator /> : null}
      <DropdownMenuLabel className="text-caption text-muted-foreground">
        {group.label}
      </DropdownMenuLabel>
      {group.items.map((m) => (
        <DropdownMenuItem
          key={m.kind}
          data-kind={m.kind}
          title={m.description}
          onSelect={() => onAdd(m.kind)}
        >
          <ManifestIcon name={m.icon} className="size-4" />
          <span className="flex min-w-0 flex-col">
            <span>{m.label}</span>
            <span className="max-w-56 truncate text-caption text-muted-foreground">
              {m.description}
            </span>
          </span>
        </DropdownMenuItem>
      ))}
    </DropdownMenuGroup>
  ));
}

function AddMenu({
  label,
  palette,
  onAdd,
}: {
  label: string;
  palette: Palette;
  onAdd: (kind: string) => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="ghost" size="sm">
          <PlusIcon aria-hidden="true" data-icon="inline-start" />
          {label}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <AddItems palette={palette} onAdd={onAdd} />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** A menu item that cannot be used, and why, under its label. */
function Unavailable({ label, reason }: { label: string; reason: string }) {
  return (
    <DropdownMenuItem disabled>
      <span className="flex min-w-0 flex-col">
        <span>{label}</span>
        <span className="max-w-56 text-caption text-muted-foreground">{reason}</span>
      </span>
    </DropdownMenuItem>
  );
}

/** A parallel's branch by what it shows: its id, or a sequence's first step and how many more. */
function branchName(branch: SpecNode): string {
  if (branch.type !== "sequence") return branch.id;
  const more = branch.steps.length - 1;
  return more > 0 ? `${branch.steps[0].id} + ${more} more` : branch.steps[0].id;
}

function StepMenu({
  node,
  canMoveUp,
  canMoveDown,
  stayReason,
  canReplace,
  targets,
  palette,
  onEditParams,
  onAdd,
  onAddBranch,
  onMove,
  onMoveTo,
  onReplace,
  onRemove,
}: {
  node: SpecNode;
  canMoveUp: boolean;
  canMoveDown: boolean;
  /** Why the node cannot be removed or moved away; `null` when it can. */
  stayReason: string | null;
  canReplace: boolean;
  targets: MoveTarget[];
  palette: Palette;
  onEditParams: () => void;
  onAdd: (kind: string) => void;
  onAddBranch: (kind: string) => void;
  onMove: (direction: "up" | "down") => void;
  onMoveTo: (target: MoveTarget) => void;
  onReplace: (kind: string) => void;
  onRemove: (node: SpecNode) => void;
}) {
  // A branch that is a sequence has no card of its own: its parallel's menu removes it.
  const removableBranches =
    node.type === "parallel" && node.branches.length > 2
      ? node.branches.filter((b) => b.type === "sequence")
      : [];
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="ghost" size="icon-xs" aria-label={`Edit step ${node.id}`}>
          <EllipsisIcon aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={onEditParams}>
          <SlidersHorizontalIcon aria-hidden="true" />
          Edit parameters
        </DropdownMenuItem>
        <DropdownMenuSub>
          <DropdownMenuSubTrigger>
            <PlusIcon aria-hidden="true" />
            Add a step after
          </DropdownMenuSubTrigger>
          <DropdownMenuSubContent>
            <AddItems palette={palette} onAdd={onAdd} />
          </DropdownMenuSubContent>
        </DropdownMenuSub>
        {node.type === "parallel" ? (
          <DropdownMenuSub>
            <DropdownMenuSubTrigger>
              <PlusIcon aria-hidden="true" />
              Add a branch
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              <AddItems palette={palette} onAdd={onAddBranch} />
            </DropdownMenuSubContent>
          </DropdownMenuSub>
        ) : null}
        <DropdownMenuSeparator />
        <DropdownMenuItem disabled={!canMoveUp} onSelect={() => onMove("up")}>
          Move up
        </DropdownMenuItem>
        <DropdownMenuItem disabled={!canMoveDown} onSelect={() => onMove("down")}>
          Move down
        </DropdownMenuItem>
        {stayReason ? (
          <Unavailable label="Move to…" reason={stayReason} />
        ) : (
          <DropdownMenuSub>
            <DropdownMenuSubTrigger disabled={targets.length === 0}>
              Move to…
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent className="max-h-80 overflow-y-auto">
              {targets.map((target) => {
                const [prefix, id] =
                  "after" in target ? ["After", target.after] : ["New branch of", target.branchOf];
                return (
                  <DropdownMenuItem key={`${prefix} ${id}`} onSelect={() => onMoveTo(target)}>
                    <span>
                      {prefix} <span className="font-mono">{id}</span>
                    </span>
                  </DropdownMenuItem>
                );
              })}
            </DropdownMenuSubContent>
          </DropdownMenuSub>
        )}
        <DropdownMenuSeparator />
        {canReplace ? (
          <DropdownMenuSub>
            <DropdownMenuSubTrigger>
              <ReplaceIcon aria-hidden="true" />
              Replace with…
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              <AddItems palette={palette} onAdd={onReplace} />
            </DropdownMenuSubContent>
          </DropdownMenuSub>
        ) : null}
        {removableBranches.length > 0 ? (
          <DropdownMenuSub>
            <DropdownMenuSubTrigger>Remove a branch</DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              {removableBranches.map((branch) => (
                <DropdownMenuItem
                  key={branch.id}
                  variant="destructive"
                  onSelect={() => onRemove(branch)}
                >
                  <span className="font-mono">{branchName(branch)}</span>
                </DropdownMenuItem>
              ))}
            </DropdownMenuSubContent>
          </DropdownMenuSub>
        ) : null}
        {stayReason ? (
          <Unavailable label="Remove" reason={stayReason} />
        ) : (
          <DropdownMenuItem variant="destructive" onSelect={() => onRemove(node)}>
            Remove
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** A node to remove, or to replace with a new node of `replaceWith`'s kind. */
interface Removal {
  node: SpecNode;
  replaceWith?: string;
}

function RemoveDialog({
  removal,
  onCancel,
  onConfirm,
}: {
  removal: Removal | null;
  onCancel: () => void;
  onConfirm: (removal: Removal) => void;
}) {
  const node = removal?.node;
  const verb = removal?.replaceWith ? "Replace" : "Remove";
  const under = node ? subtreeSize(node) - 1 : 0;
  // A branch that is a sequence is named by its steps, as its parallel's menu names it.
  const name = node ? branchName(node) : "";
  return (
    <AlertDialog open={removal !== null} onOpenChange={(open) => (open ? null : onCancel())}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {verb} <span className="font-mono">{name}</span>?
          </AlertDialogTitle>
          <AlertDialogDescription>
            {removal?.replaceWith ? `A new ${removal.replaceWith} takes its place. ` : null}
            {under > 0 ? `The ${under} ${under === 1 ? "node" : "nodes"} under it go too. ` : null}
            Undo brings it back until you save.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction variant="destructive" onClick={() => removal && onConfirm(removal)}>
            {verb}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
