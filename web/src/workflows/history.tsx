"use client";

import { DiffIcon, MoveRightIcon, PencilLineIcon, PlusIcon } from "lucide-react";
import Link from "next/link";
import { useState, type MouseEvent } from "react";

import { RelativeTime } from "@/components/display";
import { JsonView } from "@/components/json-view";
import { ErrorState, LoadingState } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { MD_UP, useMediaQuery } from "@/lib/use-media-query";
import { cn } from "@/lib/utils";
import { isKnownKind, kindLabel } from "@/runs/graph/node-kinds";

import type { WorkflowVersionItem } from "./api";
import { summarizeDiff, type NodeChange, type SpecDiff, type ValueChange } from "./diff";
import { PublishedBadge } from "./composites";

/**
 * Workflow versions (5.7): the history of a stored workflow, and what changed between two of its
 * versions, drawn on the builder's cards and listed beside them.
 */

/** The builder's URL for a version (`null`: the latest) compared with another (`null`: none). */
export function versionHref(
  workflowId: string,
  version: number | null,
  compare: number | null = null,
): string {
  const query = new URLSearchParams();
  if (version !== null) query.set("version", String(version));
  if (compare !== null) query.set("compare", String(compare));
  const qs = query.toString();
  return `/workflows/${encodeURIComponent(workflowId)}${qs ? `?${qs}` : ""}`;
}

/** What made a version, for its history row. */
export function madeBy(item: WorkflowVersionItem): string {
  if (item.restored_from !== null) return `Restored from version ${item.restored_from}`;
  if (item.base_version === null) return "Created";
  return `${item.op_count} ${item.op_count === 1 ? "change" : "changes"}`;
}

/** Every version, newest first, each opening the builder on it. `onOpen` may stop the link (to
 * ask before unsaved edits are left). */
export function HistorySheet({
  open,
  onOpenChange,
  workflowId,
  shown,
  versions,
  onOpen,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workflowId: string;
  /** The version the builder shows. */
  shown: number;
  versions: {
    data: WorkflowVersionItem[] | undefined;
    error: string | null;
    retry: () => void;
  };
  onOpen: (href: string, event: MouseEvent) => void;
}) {
  const wide = useMediaQuery(MD_UP);
  const items = versions.data;
  let body;
  if (versions.error) body = <ErrorState message={versions.error} onRetry={versions.retry} />;
  else if (!items) body = <LoadingState rows={4} label="Loading versions…" />;
  else {
    const latest = items[0]?.version;
    body = (
      <ol aria-label="Versions" data-testid="version-list" className="flex flex-col gap-1">
        {items.map((item) => {
          const href = versionHref(workflowId, item.version === latest ? null : item.version);
          const current = item.version === shown;
          return (
            <li key={item.version}>
              <Link
                href={href}
                aria-current={current ? "page" : undefined}
                onClick={(event) => onOpen(href, event)}
                className={cn(
                  "flex flex-col gap-0.5 rounded-md border border-transparent px-3 py-2 outline-none hover:bg-surface-subtle focus-visible:ring-2 focus-visible:ring-ring",
                  current && "border-border bg-surface-subtle",
                )}
              >
                <span className="flex items-center gap-2 text-body font-medium text-foreground">
                  Version {item.version}
                  {item.version === latest ? <Badge variant="secondary">Latest</Badge> : null}
                  {item.published_at != null ? <PublishedBadge /> : null}
                  {current ? <span className="sr-only">(shown)</span> : null}
                </span>
                <span className="flex flex-wrap gap-x-1 text-meta text-foreground-secondary">
                  <span>{madeBy(item)}</span>
                  <span aria-hidden="true">·</span>
                  <RelativeTime iso={item.created_at} focusable={false} />
                </span>
              </Link>
            </li>
          );
        })}
      </ol>
    );
  }
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side={wide ? "right" : "bottom"}
        size="sm"
        className="max-h-svh gap-0 p-0 data-[side=bottom]:max-h-[80svh]"
      >
        <SheetHeader className="border-b">
          <SheetTitle>History</SheetTitle>
          <SheetDescription>
            Every saved version. Older versions open read-only, to restore or run.
          </SheetDescription>
        </SheetHeader>
        <div className="overflow-y-auto p-2">{body}</div>
      </SheetContent>
    </Sheet>
  );
}

const MARK: Record<NodeChange["kind"], { label: string; icon: typeof PlusIcon }> = {
  added: { label: "Added", icon: PlusIcon },
  changed: { label: "Changed", icon: PencilLineIcon },
  moved: { label: "Moved", icon: MoveRightIcon },
};

/** A card's mark: how its node differs from the version compared with. Neutral: colour is for
 * status only. */
export function DiffBadge({ change }: { change: NodeChange }) {
  const { label, icon: Icon } = MARK[change.kind];
  return (
    <Badge variant="secondary" className="h-5 px-1.5" data-testid="diff-badge">
      <Icon aria-hidden="true" data-icon="inline-start" />
      {label}
    </Badge>
  );
}

/** A value of a version as text: a string as written, a list or object as JSON. */
function Value({ value }: { value: unknown }) {
  if (value === undefined || value === null) {
    return <span className="text-muted-foreground">Unset</span>;
  }
  if (typeof value === "object") return <JsonView value={value} openDepth={1} />;
  return <span className="break-words whitespace-pre-wrap text-foreground">{String(value)}</span>;
}

/** Each changed value: its path, then what it was and what it is. */
export function ValueChanges({ changes }: { changes: ValueChange[] }) {
  return (
    <dl className="flex flex-col gap-3">
      {changes.map((change) => (
        <div key={change.path} className="flex flex-col gap-1 text-meta">
          <dt className="font-mono text-caption font-medium text-foreground">{change.path}</dt>
          <dd className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 gap-y-1">
            <span className="text-muted-foreground">Before</span>
            <Value value={change.before} />
            <span className="text-muted-foreground">After</span>
            <Value value={change.after} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** Everything that changed, in one list: nodes (each id selecting its card), the nodes that are
 * gone, and the workflow's own fields. */
function ChangeList({ diff, onShow }: { diff: SpecDiff; onShow: (nodeId: string) => void }) {
  const nodes = [...diff.nodes];
  return (
    <div data-testid="change-list" className="flex flex-col gap-4">
      {nodes.length > 0 ? (
        <ul aria-label="Changed steps" className="flex flex-col gap-2">
          {nodes.map(([id, change]) => (
            <li key={id} className="flex items-center gap-2 text-meta">
              <button
                type="button"
                onClick={() => onShow(id)}
                className="min-w-0 truncate rounded-sm font-mono text-caption font-medium outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
              >
                {id}
              </button>
              <DiffBadge change={change} />
              {change.kind === "changed" ? (
                <span className="min-w-0 truncate font-mono text-caption text-foreground-secondary">
                  {change.changes.map((c) => c.path).join(", ")}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {diff.removed.length > 0 ? (
        <ul aria-label="Removed steps" className="flex flex-col gap-2">
          {diff.removed.map(({ id, type }) => (
            <li key={id} className="flex items-center gap-2 text-meta">
              <span className="min-w-0 truncate font-mono text-caption font-medium">{id}</span>
              <span className="text-foreground-secondary">
                Removed · {isKnownKind(type) ? kindLabel(type) : type}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {diff.document.length > 0 ? (
        <section aria-label="Workflow" className="flex flex-col gap-2">
          <h3 className="text-caption font-medium text-muted-foreground">Workflow</h3>
          <ValueChanges changes={diff.document} />
        </section>
      ) : null}
      {nodes.length + diff.removed.length + diff.document.length === 0 ? (
        <p className="text-meta text-foreground-secondary">Nothing differs.</p>
      ) : null}
    </div>
  );
}

/** The status line's summary of the comparison ("2 added · 1 removed"), opening the list of
 * changes: a popover from 768 px, a bottom sheet below. */
export function ChangesStatus({
  diff,
  compared,
  onShow,
}: {
  diff: SpecDiff;
  compared: number;
  onShow: (nodeId: string) => void;
}) {
  const md = useMediaQuery(MD_UP);
  const [open, setOpen] = useState(false);
  const summary = summarizeDiff(diff);
  const list = (
    <ChangeList
      diff={diff}
      onShow={(id) => {
        setOpen(false);
        onShow(id);
      }}
    />
  );
  const trigger = (
    <button
      type="button"
      data-testid="diff-summary"
      onClick={() => setOpen(true)}
      className="flex items-center gap-1 rounded-sm underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
    >
      <DiffIcon aria-hidden="true" className="size-3.5 shrink-0 text-muted-foreground" />
      {summary}
      <span className="sr-only"> since version {compared}</span>
    </button>
  );
  if (md) {
    return (
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>{trigger}</PopoverTrigger>
        <PopoverContent
          align="start"
          className="max-h-96 w-96 max-w-[calc(100vw-2rem)] overflow-y-auto"
        >
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
            <SheetTitle>Changes</SheetTitle>
            <SheetDescription>What differs from version {compared}.</SheetDescription>
          </SheetHeader>
          <div className="overflow-y-auto p-4">{list}</div>
        </SheetContent>
      </Sheet>
    </>
  );
}
