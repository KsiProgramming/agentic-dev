"use client";

import { CircleDashedIcon } from "lucide-react";
import { useMemo, useRef } from "react";

import { EmptyState } from "@/components/states";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { MD_UP, useMediaQuery } from "@/lib/use-media-query";

import { StepBody, type StepViewOptions } from "../console/step-view";
import type { Step } from "../timeline";
import { kindLabel, NodeStatusLine } from "./graph-nodes";
import { focusStep, nodeStatuses } from "./node-status";
import { allSpecNodes, type WorkflowSpec } from "./spec-graph";

/**
 * What one node of the graph did, in a sheet: the same step view as the timeline. A node inside
 * a map or a loop shows one entry per item or iteration.
 */
export function NodeDetailSheet({
  nodeId,
  spec,
  steps,
  options,
  onClose,
}: {
  /** The node to show; `null` keeps the sheet closed. */
  nodeId: string | null;
  spec: WorkflowSpec;
  steps: Step[];
  options: StepViewOptions;
  onClose: () => void;
}) {
  const wide = useMediaQuery(MD_UP);
  const returnTo = useRef<HTMLElement | null>(null);
  const node = useMemo(
    () => (nodeId ? allSpecNodes(spec).find((n) => n.id === nodeId) : undefined),
    [spec, nodeId],
  );
  const focused = nodeId ? focusStep(steps, nodeId) : null;
  const status = nodeId ? nodeStatuses(spec, steps).get(nodeId)?.status : undefined;

  return (
    <Sheet open={node !== undefined} onOpenChange={(open) => (open ? null : onClose())}>
      {node ? (
        <SheetContent
          side={wide ? "right" : "bottom"}
          className="data-[side=bottom]:max-h-[85svh] data-[side=right]:w-full! data-[side=right]:sm:max-w-[480px]!"
          data-testid="node-detail"
          // Focus the sheet, not its first control: that may be a value whose tooltip opens on
          // focus, and the open tooltip would take the first Escape.
          onOpenAutoFocus={(event) => {
            const active = document.activeElement;
            returnTo.current = active instanceof HTMLElement ? active : null;
            event.preventDefault();
            (event.currentTarget as HTMLElement).focus();
          }}
          // The sheet has no trigger for Radix to refocus: go back to the node it was opened from.
          onCloseAutoFocus={(event) => {
            if (!returnTo.current?.isConnected) return;
            event.preventDefault();
            returnTo.current.focus();
          }}
        >
          <SheetHeader className="border-b pr-12">
            <SheetTitle className="font-mono break-all">{node.id}</SheetTitle>
            <SheetDescription className="flex flex-wrap items-center gap-2">
              <span>{kindLabel(node.type)}</span>
              {status ? <NodeStatusLine status={status} /> : null}
            </SheetDescription>
          </SheetHeader>
          <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 pb-4">
            {focused ? (
              <StepBody step={focused} options={options} />
            ) : (
              <EmptyState icon={CircleDashedIcon} message="This step has not run yet." />
            )}
          </div>
        </SheetContent>
      ) : null}
    </Sheet>
  );
}
