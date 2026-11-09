import {
  BotIcon,
  BoxIcon,
  LayersIcon,
  MergeIcon,
  NetworkIcon,
  RepeatIcon,
  ShieldCheckIcon,
  SignpostIcon,
  SplitIcon,
  WorkflowIcon,
  WrenchIcon,
  type LucideIcon,
} from "lucide-react";

import { stepBadge } from "../console/step-status";
import type { NodeStatus } from "./node-status";
import type { NodeKind } from "./spec-graph";

const KIND: Record<NodeKind, { icon: LucideIcon; label: string }> = {
  agent: { icon: BotIcon, label: "agent" },
  tool: { icon: WrenchIcon, label: "tool" },
  gate: { icon: ShieldCheckIcon, label: "gate" },
  reduce: { icon: MergeIcon, label: "reduce" },
  loop: { icon: RepeatIcon, label: "loop" },
  map: { icon: LayersIcon, label: "map" },
  parallel: { icon: SplitIcon, label: "parallel" },
  router: { icon: SignpostIcon, label: "router" },
  orchestrator: { icon: NetworkIcon, label: "orchestrator" },
  subflow: { icon: WorkflowIcon, label: "subflow" },
  sequence: { icon: LayersIcon, label: "sequence" },
};

/** Whether this app has its own icon and name for `kind`. A kind the engine added later (5.3)
 * has not: it is drawn as a box under its own name, or from its manifest in the builder. */
export function isKnownKind(kind: string): kind is NodeKind {
  return Object.hasOwn(KIND, kind);
}

/** A node kind in a word: "agent", "map"; the kind itself for one this app does not know. */
export function kindLabel(kind: NodeKind): string {
  return isKnownKind(kind) ? KIND[kind].label : kind;
}

/** A node kind's icon, beside its name; a box for one this app does not know. */
export function KindIcon({ kind, className }: { kind: NodeKind; className?: string }) {
  const Icon = isKnownKind(kind) ? KIND[kind].icon : BoxIcon;
  return <Icon aria-hidden="true" className={className} />;
}

/** A node's status in words, including the two only the map has. */
export function statusLabel(status: NodeStatus): string {
  if (status === "not_started") return "Not started";
  if (status === "skipped") return "Skipped";
  return stepBadge(status).label;
}
