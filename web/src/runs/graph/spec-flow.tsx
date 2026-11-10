"use client";

import { useId, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";

import { flowLayout, type FlowEdge } from "./flow-layout";
import type { WorkflowSpec } from "./spec-graph";
import { SpecTree, type MapNode } from "./spec-tree";

/**
 * A workflow drawn as a flow read left to right (5.9, design-language.md → Run map): each card in
 * its grid cell (`flowLayout`), framed lanes behind a map's, an orchestrator's or a call's
 * cards, and the edges in an SVG under them. The cards are the caller's (`renderCard`): the run
 * map's statuses, the builder's menus. Edges are drawn from where the cards are, measured once
 * they are laid out, so a card taller than the others (an orchestrator's tasks) moves its edges
 * with it. Edges never carry a status colour; a route not taken is dashed.
 */

/** Below this pane width the flow does not fit: the vertical tree is drawn instead. */
export const FLOW_MIN_WIDTH = 560;

/** Where a card's edges meet it: the middle of its 56 px card (`CARD`), whatever hangs under. */
const ANCHOR_Y = 28;
/** How far before its target a join's or fork's vertical runs, in the column gap. */
const ELBOW = 16;
/** A card's width (`CARD`, `w-52`) and the column gap (`gap-x-7`): how many columns fit. */
const CARD_WIDTH = 208;
const COLUMN_GAP = 28;

/** How many columns of cards fit in `width` px. */
export function columnsIn(width: number): number {
  return Math.max(1, Math.floor((width + COLUMN_GAP) / (CARD_WIDTH + COLUMN_GAP)));
}

interface Drawn {
  key: string;
  /** The cards it joins, as `data-from` and `data-to`: tests compare two views' graphs (6.8). */
  from: string;
  to: string;
  d: string;
  kind: FlowEdge["kind"];
  dashed: boolean;
  label: { text: string; x: number; y: number } | null;
}

export function SpecFlow({
  spec,
  renderCard,
  isSkipped,
  width,
}: {
  spec: WorkflowSpec;
  renderCard: (node: MapNode) => ReactNode;
  /** Whether a router's route (its `routeNodeId`) was not taken: its fork is dashed. */
  isSkipped?: (route: string) => boolean;
  /** The pane's width: the root sequence wraps onto a new row past it. Unset: one row. */
  width?: number;
}) {
  const maxCols = width ? columnsIn(width) : undefined;
  const layout = useMemo(() => flowLayout(spec, maxCols), [spec, maxCols]);
  const box = useRef<HTMLDivElement>(null);
  const cells = useRef(new Map<string, HTMLDivElement>());
  const [drawn, setDrawn] = useState<{ paths: Drawn[]; width: number; height: number }>({
    paths: [],
    width: 0,
    height: 0,
  });
  const marker = useId().replaceAll(":", "");

  useLayoutEffect(() => {
    const root = box.current;
    if (!root) return;
    const draw = () => {
      const origin = root.getBoundingClientRect();
      const at = (id: string) => {
        const r = cells.current.get(id)?.getBoundingClientRect();
        if (!r) return null;
        return {
          left: r.left - origin.left,
          right: r.right - origin.left,
          top: r.top - origin.top,
          bottom: r.bottom - origin.top,
        };
      };
      const paths: Drawn[] = [];
      for (const [i, edge] of layout.edges.entries()) {
        const from = at(edge.from);
        const to = at(edge.to);
        if (!from || !to) continue;
        const dashed = edge.route !== null && (isSkipped?.(edge.route) ?? false);
        if (edge.kind === "back") {
          // Under the lane, from the end of the loop's body back to the loop.
          const y = Math.max(from.bottom, to.bottom) + 14;
          const fx = (from.left + from.right) / 2;
          const tx = (to.left + to.right) / 2;
          paths.push({
            key: `${i}`,
            from: edge.from,
            to: edge.to,
            d: `M ${fx} ${from.bottom} V ${y} H ${tx} V ${to.bottom}`,
            kind: edge.kind,
            dashed,
            label: edge.label ? { text: edge.label, x: (fx + tx) / 2, y: y + 14 } : null,
          });
          continue;
        }
        if (edge.kind === "wrap") {
          // From the end of one row, down into the gap above the next, back to its start.
          const y1 = from.top + ANCHOR_Y;
          const gap = to.top - 36;
          const y2 = to.top + ANCHOR_Y;
          paths.push({
            key: `${i}`,
            from: edge.from,
            to: edge.to,
            d: `M ${from.right} ${y1} H ${from.right + 6} V ${gap} H ${to.left - 12} V ${y2} H ${to.left}`,
            kind: edge.kind,
            dashed: false,
            label: null,
          });
          continue;
        }
        const x1 = from.right;
        const y1 = from.top + ANCHOR_Y;
        const x2 = to.left;
        const y2 = to.top + ANCHOR_Y;
        const elbow = Math.max(x1 + 8, x2 - ELBOW);
        const d = y1 === y2 ? `M ${x1} ${y1} H ${x2}` : `M ${x1} ${y1} H ${elbow} V ${y2} H ${x2}`;
        paths.push({
          key: `${i}`,
          from: edge.from,
          to: edge.to,
          d,
          kind: edge.kind,
          dashed,
          // A route's name sits over its first card, clear of the lines.
          label: edge.label ? { text: edge.label, x: x2, y: to.top - 6 } : null,
        });
      }
      setDrawn({ paths, width: root.scrollWidth, height: root.scrollHeight });
    };
    draw();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(draw);
    observer.observe(root);
    for (const cell of cells.current.values()) observer.observe(cell);
    return () => observer.disconnect();
  }, [layout, isSkipped]);

  return (
    <div
      ref={box}
      data-testid="spec-flow"
      className="relative inline-grid gap-x-7 gap-y-16 pt-6 pr-1 pb-10 pl-3"
      style={{
        gridTemplateColumns: `repeat(${layout.cols}, max-content)`,
        gridTemplateRows: `repeat(${layout.rows}, auto)`,
      }}
    >
      {layout.lanes.map((lane) => (
        <div
          key={`lane-${lane.id}`}
          aria-hidden="true"
          data-testid="flow-lane"
          className="pointer-events-none relative -m-3 rounded-xl border border-dashed border-border-strong"
          style={{
            gridColumn: `${lane.col + 1} / span ${lane.cols}`,
            gridRow: `${lane.row + 1} / span ${lane.rows}`,
          }}
        >
          <span className="absolute -top-5 left-2 text-caption text-muted-foreground">
            {lane.label}
          </span>
        </div>
      ))}
      <svg
        aria-hidden="true"
        className="pointer-events-none absolute top-0 left-0 overflow-visible"
        width={drawn.width}
        height={drawn.height}
      >
        <defs>
          <marker
            id={marker}
            viewBox="0 0 8 8"
            refX="8"
            refY="4"
            markerWidth="8"
            markerHeight="8"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 8 4 L 0 8 z" className="fill-border-strong" />
          </marker>
        </defs>
        {drawn.paths.map((p) => (
          <g key={p.key} data-edge={p.kind} data-from={p.from} data-to={p.to}>
            <path
              d={p.d}
              fill="none"
              className="stroke-border-strong"
              strokeWidth={1}
              strokeDasharray={p.dashed || p.kind === "back" ? "4 4" : undefined}
              markerEnd={`url(#${marker})`}
            />
            {p.label ? (
              <text
                x={p.label.x}
                y={p.label.y}
                textAnchor={p.kind === "back" ? "middle" : "start"}
                className="fill-muted-foreground font-mono text-kbd"
              >
                {p.label.text}
              </text>
            ) : null}
          </g>
        ))}
      </svg>
      {layout.cards.map(({ node, col, row }) => (
        <div
          key={node.id}
          ref={(el) => {
            if (el) cells.current.set(node.id, el);
            else cells.current.delete(node.id);
          }}
          data-flow-card={node.id}
          className="relative self-start"
          style={{ gridColumn: col + 1, gridRow: row + 1 }}
        >
          {renderCard(node)}
        </div>
      ))}
    </div>
  );
}

/**
 * A workflow drawn for its pane's width: the flow from `FLOW_MIN_WIDTH`, the vertical tree
 * below (a phone scrolls down, not sideways). `layout` forces one (tests, previews).
 */
export function SpecView({
  spec,
  renderCard,
  isSkipped,
  layout,
}: {
  spec: WorkflowSpec;
  renderCard: (node: MapNode) => ReactNode;
  isSkipped?: (route: string) => boolean;
  layout?: "flow" | "tree";
}) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const wide = width >= FLOW_MIN_WIDTH;
  useLayoutEffect(() => {
    const root = box.current;
    if (!root || typeof ResizeObserver === "undefined") return;
    const measure = () => setWidth(root.clientWidth);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(root);
    return () => observer.disconnect();
  }, []);
  const flow = layout ? layout === "flow" : wide;
  return (
    <div ref={box} className={cn("min-w-0", flow && "w-full")}>
      {flow ? (
        <SpecFlow
          spec={spec}
          renderCard={renderCard}
          isSkipped={isSkipped}
          // The flow's own side padding (16 px) is not room for cards.
          width={width > 0 ? width - 16 : undefined}
        />
      ) : (
        <SpecTree spec={spec} renderCard={renderCard} />
      )}
    </div>
  );
}
