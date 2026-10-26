"use client";

import { Controls, ReactFlow } from "@xyflow/react";
import { useTheme } from "next-themes";
import { useMemo } from "react";

import type { Step } from "../timeline";
import { GraphContext, NODE_TYPES } from "./graph-nodes";
import { nodeStatuses } from "./node-status";
import { specToGraph, type WorkflowSpec } from "./spec-graph";

/**
 * The run's workflow drawn read-only, each node coloured by its live status. Clicking a node (or
 * Enter on it) calls `onOpen` with its id. The graph pans and zooms inside its own box, so the
 * page never scrolls sideways.
 */
export function RunGraph({
  spec,
  steps,
  onOpen,
}: {
  spec: WorkflowSpec;
  steps: Step[];
  onOpen: (nodeId: string) => void;
}) {
  // Laid out once per spec; new events only change the states the nodes read.
  const graph = useMemo(() => {
    const { nodes, edges } = specToGraph(spec);
    // React Flow turns pointer events off on a node that is neither selectable nor draggable:
    // the pane under it would take the click. Each node is a button of its own, so keep them.
    return {
      nodes: nodes.map((node) => ({ ...node, style: { pointerEvents: "all" as const } })),
      edges,
    };
  }, [spec]);
  const states = useMemo(() => nodeStatuses(spec, steps), [spec, steps]);
  const context = useMemo(() => ({ states, open: onOpen }), [states, onOpen]);
  const { resolvedTheme } = useTheme();

  return (
    <GraphContext value={context}>
      <div
        data-testid="run-graph"
        role="region"
        aria-label="Workflow graph"
        className="h-[min(70svh,720px)] min-h-80 w-full overflow-hidden rounded-lg border bg-background"
      >
        <ReactFlow
          nodes={graph.nodes}
          edges={graph.edges}
          nodeTypes={NODE_TYPES}
          colorMode={resolvedTheme === "dark" ? "dark" : "light"}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          minZoom={0.2}
          maxZoom={1.5}
          // Read only: nothing moves, connects or is deleted. Each node is a button of its own,
          // so React Flow's own node focus and selection are off (one tab stop per node).
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          nodesFocusable={false}
          edgesFocusable={false}
          deleteKeyCode={null}
          selectionKeyCode={null}
          multiSelectionKeyCode={null}
        >
          <Controls showInteractive={false} position="bottom-right" />
        </ReactFlow>
      </div>
    </GraphContext>
  );
}
