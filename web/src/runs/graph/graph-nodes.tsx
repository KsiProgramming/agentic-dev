"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import {
  BotIcon,
  CircleDashedIcon,
  LayersIcon,
  MergeIcon,
  RepeatIcon,
  ShieldCheckIcon,
  SplitIcon,
  WrenchIcon,
  type LucideIcon,
} from "lucide-react";
import { createContext, useContext } from "react";

import { cn } from "@/lib/utils";

import { StatusIcon } from "../console/rail";
import { stepBadge } from "../console/step-status";
import type { NodeState, NodeStatus } from "./node-status";
import type { ContainerNode, LeafNode, NodeKind } from "./spec-graph";

/** What the drawn nodes read: each node's state, which one is selected, and how to select one.
 * Passed by context so a status change re-renders the nodes without laying the graph out
 * again. */
export interface GraphContextValue {
  states: Map<string, NodeState>;
  selected: string | null;
  open: (nodeId: string) => void;
}

export const GraphContext = createContext<GraphContextValue>({
  states: new Map(),
  selected: null,
  open: () => {},
});

const KIND: Record<NodeKind, { icon: LucideIcon; label: string }> = {
  agent: { icon: BotIcon, label: "agent" },
  tool: { icon: WrenchIcon, label: "tool" },
  gate: { icon: ShieldCheckIcon, label: "gate" },
  reduce: { icon: MergeIcon, label: "reduce" },
  loop: { icon: RepeatIcon, label: "loop" },
  map: { icon: LayersIcon, label: "map" },
  parallel: { icon: SplitIcon, label: "parallel" },
  sequence: { icon: LayersIcon, label: "sequence" },
};

export function kindLabel(kind: NodeKind): string {
  return KIND[kind].label;
}

/** A node kind's icon, beside its name. */
export function KindIcon({ kind, className }: { kind: NodeKind; className?: string }) {
  const Icon = KIND[kind].icon;
  return <Icon aria-hidden="true" className={className} />;
}

export function statusLabel(status: NodeStatus): string {
  return status === "not_started" ? "Not started" : stepBadge(status).label;
}

/** Only states that need attention or are going on tint the node's border. */
const BORDER: Partial<Record<NodeStatus, string>> = {
  running: "border-status-running",
  waiting: "border-status-waiting",
  failed: "border-status-failed",
};

/** A node's status: its icon and label (never colour alone). */
export function NodeStatusLine({ status }: { status: NodeStatus }) {
  return (
    <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground">
      {status === "not_started" ? (
        <CircleDashedIcon aria-hidden="true" className="size-3.5" />
      ) : (
        <StatusIcon status={status} small />
      )}
      {statusLabel(status)}
    </span>
  );
}

function useNodeState(nodeId: string) {
  const { states, selected, open } = useContext(GraphContext);
  const state = states.get(nodeId) ?? { status: "not_started" as const, summary: null };
  return { state, selected: selected === nodeId, open: () => open(nodeId) };
}

/** The node whose step the console shows. */
const SELECTED = "ring-2 ring-primary";

/** Hidden handles: edges need them, nobody connects anything. */
function Handles() {
  return (
    <>
      <Handle type="target" position={Position.Top} isConnectable={false} className="opacity-0" />
      <Handle
        type="source"
        position={Position.Bottom}
        isConnectable={false}
        className="opacity-0"
      />
    </>
  );
}

/** The node's visible text in the order it is shown (id, status, second line), then what only
 * the icons say: the name must contain the visible label (WCAG 2.5.3, axe
 * label-content-name-mismatch). */
function accessibleName(nodeId: string, kind: NodeKind, state: NodeState, line: string): string {
  const parts = [nodeId, statusLabel(state.status)];
  if (line) parts.push(line);
  if (state.summary && state.summary !== line) parts.push(state.summary);
  parts.push(kindLabel(kind));
  return parts.join(", ");
}

const BUTTON =
  "w-full min-w-0 cursor-pointer text-left outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** An agent, tool, gate or reduce: a card that selects what the node did. */
export function LeafNodeView({ data }: NodeProps<LeafNode>) {
  const { state, selected, open } = useNodeState(data.nodeId);
  const Icon = KIND[data.kind].icon;
  return (
    <>
      <Handles />
      <button
        type="button"
        onClick={open}
        aria-label={accessibleName(data.nodeId, data.kind, state, data.detail)}
        aria-pressed={selected}
        data-testid="graph-node"
        data-node-id={data.nodeId}
        data-status={state.status}
        className={cn(
          BUTTON,
          "flex h-full flex-col justify-center gap-1 rounded-lg border bg-card px-3 shadow-xs hover:bg-accent",
          BORDER[state.status],
          selected && SELECTED,
        )}
      >
        <span className="flex min-w-0 items-center gap-2">
          <Icon aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate font-mono text-meta font-medium">
            {data.nodeId}
          </span>{" "}
          <NodeStatusLine status={state.status} />
        </span>{" "}
        <span className="truncate text-xs text-muted-foreground">{data.detail}</span>
      </button>
    </>
  );
}

/** A loop, map or parallel: a box holding its body (a parallel's branches side by side), its
 * header selecting what the node did. */
export function ContainerNodeView({ data }: NodeProps<ContainerNode>) {
  const { state, selected, open } = useNodeState(data.nodeId);
  const Icon = KIND[data.kind].icon;
  const line = state.summary ?? data.detail;
  return (
    <div
      className={cn(
        "h-full w-full rounded-lg border border-dashed bg-muted/40",
        BORDER[state.status],
      )}
    >
      <Handles />
      <button
        type="button"
        onClick={open}
        aria-label={accessibleName(data.nodeId, data.kind, state, line)}
        aria-pressed={selected}
        data-testid="graph-node"
        data-node-id={data.nodeId}
        data-status={state.status}
        className={cn(
          BUTTON,
          "flex h-14 flex-col justify-center gap-1 rounded-t-lg px-3",
          selected && SELECTED,
        )}
      >
        <span className="flex min-w-0 items-center gap-2">
          <Icon aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate font-mono text-meta font-medium">
            {data.nodeId}
          </span>{" "}
          <NodeStatusLine status={state.status} />
        </span>{" "}
        <span className="truncate text-xs text-muted-foreground tabular-nums">{line}</span>
      </button>
    </div>
  );
}

export const NODE_TYPES = { leaf: LeafNodeView, container: ContainerNodeView };
