"use client";

import { Controls, ReactFlow } from "@xyflow/react";
import { useTheme } from "next-themes";
import { useEffect, useMemo, useState } from "react";

import { ErrorState, LoadingState } from "@/components/states";

import type { Step } from "../timeline";
import { GraphContext, NODE_TYPES } from "./graph-nodes";
import { nodeStatuses, routeStates } from "./node-status";
import { layoutSpec, type SpecGraph, type WorkflowSpec } from "./spec-graph";

type Layout =
  | { spec: WorkflowSpec; graph: SpecGraph; error: null }
  | { spec: WorkflowSpec; graph: null; error: string };

/** `spec` laid out by ELK (async), or why it could not be; `null` while it runs. `retry` lays
 * it out again. */
function useLayout(spec: WorkflowSpec): { layout: Layout | null; retry: () => void } {
  const [layout, setLayout] = useState<Layout | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    layoutSpec(spec).then(
      (graph) => live && setLayout({ spec, graph, error: null }),
      (error: unknown) => live && setLayout({ spec, graph: null, error: String(error) }),
    );
    return () => {
      live = false;
    };
  }, [spec, attempt]);
  // A layout of an earlier spec is not this one's.
  return {
    layout: layout?.spec === spec ? layout : null,
    retry: () => {
      setLayout(null);
      setAttempt((n) => n + 1);
    },
  };
}

/**
 * The run's workflow drawn read-only, each node coloured by its live status. Clicking a node (or
 * Enter on it) calls `onOpen` with its id; `selected` is marked. The graph pans and zooms inside
 * its own box, so the page never scrolls sideways.
 */
export function RunGraph({
  spec,
  steps,
  selected = null,
  onOpen,
}: {
  spec: WorkflowSpec;
  steps: Step[];
  selected?: string | null;
  onOpen: (nodeId: string) => void;
}) {
  // Laid out once per spec; new events only change the states the nodes read.
  const { layout, retry } = useLayout(spec);
  const graph = useMemo(() => {
    if (!layout?.graph) return null;
    const { nodes, edges } = layout.graph;
    // React Flow turns pointer events off on a node that is neither selectable nor draggable:
    // the pane under it would take the click. Each node is a button of its own, so keep them.
    return {
      nodes: nodes.map((node) => ({ ...node, style: { pointerEvents: "all" as const } })),
      edges,
    };
  }, [layout]);
  const states = useMemo(
    () => new Map([...nodeStatuses(spec, steps), ...routeStates(spec, steps)]),
    [spec, steps],
  );
  const context = useMemo(() => ({ states, selected, open: onOpen }), [states, selected, onOpen]);
  const { resolvedTheme } = useTheme();

  if (layout?.error) {
    return <ErrorState message="Could not draw the workflow graph." onRetry={retry} />;
  }
  if (!graph) return <LoadingState label="Drawing the workflow graph…" />;

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
          // Apart from the controls, so neither crowds the other's 24 px target.
          attributionPosition="bottom-left"
        >
          <Controls showInteractive={false} position="bottom-right" />
        </ReactFlow>
      </div>
    </GraphContext>
  );
}
