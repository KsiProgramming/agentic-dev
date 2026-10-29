import {
  BotIcon,
  LayersIcon,
  MergeIcon,
  RepeatIcon,
  ShieldCheckIcon,
  SignpostIcon,
  SplitIcon,
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
  sequence: { icon: LayersIcon, label: "sequence" },
};

/** A node kind in a word: "agent", "map". */
export function kindLabel(kind: NodeKind): string {
  return KIND[kind].label;
}

/** A node kind's icon, beside its name. */
export function KindIcon({ kind, className }: { kind: NodeKind; className?: string }) {
  const Icon = KIND[kind].icon;
  return <Icon aria-hidden="true" className={className} />;
}

/** A node's status in words, including the two only the map has. */
export function statusLabel(status: NodeStatus): string {
  if (status === "not_started") return "Not started";
  if (status === "skipped") return "Skipped";
  return stepBadge(status).label;
}
