"use client";

import {
  ArrowRightLeftIcon,
  FileDiffIcon,
  FileMinusIcon,
  FilePlusIcon,
  RotateCcwIcon,
  type LucideIcon,
} from "lucide-react";
import dynamic from "next/dynamic";
import { Component, useId, useState, type ReactNode } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { fileKey, type FileChange, type FileChangeStatus, type NotEditableReason } from "../gates";

const DiffView = dynamic(() => import("./diff-view"), {
  ssr: false,
  loading: () => <DiffSkeleton />,
});

const STATUS: Record<FileChangeStatus, { icon: LucideIcon; label: string }> = {
  added: { icon: FilePlusIcon, label: "Added" },
  modified: { icon: FileDiffIcon, label: "Modified" },
  deleted: { icon: FileMinusIcon, label: "Deleted" },
  renamed: { icon: ArrowRightLeftIcon, label: "Renamed" },
};

/** Why a file has no diff to edit, for people. */
export const READ_ONLY_REASON: Record<NotEditableReason, string> = {
  binary: "Binary file: not shown.",
  too_large: "Too large to show (over 256 KB).",
  over_limit: "Past the review limit (50 files, 512 KB in all): not shown.",
  deleted: "Deleted: nothing to edit.",
  renamed: "Renamed: shown in the pull request, not here.",
};

/** One file of a gate as the files view shows it: its change, the two texts to compare and
 * whether the approver edited it. */
export interface GateFile {
  change: FileChange;
  original: string;
  modified: string;
  edited: boolean;
}

export function StatusLabel({ status }: { status: FileChangeStatus }) {
  const { icon: Icon, label } = STATUS[status];
  return (
    <span className="inline-flex items-center gap-1 text-caption text-muted-foreground">
      <Icon aria-hidden="true" className="size-3.5" />
      {label}
    </span>
  );
}

function DiffSkeleton() {
  return (
    <div className="flex h-full flex-col gap-2 p-4" data-testid="diff-loading">
      <Skeleton className="h-4 w-1/3" />
      <Skeleton className="h-4 w-2/3" />
      <Skeleton className="h-4 w-1/2" />
    </div>
  );
}

/** Shows the error state, with Retry, if the editor cannot be loaded. */
class DiffBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="p-4">
        <Alert variant="destructive">
          <AlertDescription className="flex flex-wrap items-center gap-2">
            The editor could not be loaded.
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => this.setState({ failed: false })}
            >
              Retry
            </Button>
          </AlertDescription>
        </Alert>
      </div>
    );
  }
}

/**
 * A gate's changed files (tech-stack → Review sheet): a list (a picker below 1024 px) and the
 * selected file's diff. With `onEdit`, editable files take edits on their modified side, and
 * edited ones can be discarded.
 */
export function GateFilesView({
  files,
  wide,
  onEdit,
  onDiscard,
}: {
  files: GateFile[];
  /** From 1024 px: the list beside a side-by-side diff; below, a picker above an inline one. */
  wide: boolean;
  onEdit?: (change: FileChange, text: string) => void;
  onDiscard?: (change: FileChange) => void;
}) {
  const pickerId = useId();
  const [selectedKey, setSelectedKey] = useState(() => {
    const first = files.find((f) => f.change.editable) ?? files[0];
    return first ? fileKey(first.change) : null;
  });
  // Bumped when a file's edits are discarded, so its editor starts again from the original.
  const [resets, setResets] = useState<Record<string, number>>({});
  const selected = files.find((f) => fileKey(f.change) === selectedKey) ?? files[0];

  if (!selected) {
    return <p className="p-4 text-muted-foreground">No files changed.</p>;
  }
  const key = fileKey(selected.change);
  const editable = onEdit !== undefined && selected.change.editable;

  return (
    <div className={cn("flex min-h-0 flex-1", wide ? "flex-row" : "flex-col")}>
      {wide ? (
        <nav aria-label="Changed files" className="w-72 shrink-0 overflow-y-auto border-r">
          <ul className="flex flex-col py-1">
            {files.map((file) => {
              const current = fileKey(file.change) === key;
              return (
                <li key={fileKey(file.change)}>
                  <button
                    type="button"
                    aria-current={current ? "true" : undefined}
                    onClick={() => setSelectedKey(fileKey(file.change))}
                    className={cn(
                      "flex w-full flex-col gap-0.5 px-3 py-2 text-left outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:ring-inset",
                      current && "bg-muted",
                    )}
                  >
                    <span className="font-mono text-meta break-all">{file.change.path}</span>
                    <span className="flex flex-wrap items-center gap-2">
                      <StatusLabel status={file.change.status} />
                      {file.edited ? <Badge variant="secondary">Edited</Badge> : null}
                      {!file.change.editable ? (
                        <span className="text-caption text-muted-foreground">Read-only</span>
                      ) : null}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>
      ) : (
        <div className="flex flex-col gap-1 border-b px-4 py-2">
          <label htmlFor={pickerId} className="text-caption text-muted-foreground">
            File {files.indexOf(selected) + 1} of {files.length}
          </label>
          <NativeSelect
            id={pickerId}
            className="w-full"
            value={key}
            onChange={(e) => setSelectedKey(e.target.value)}
          >
            {files.map((file) => (
              <NativeSelectOption key={fileKey(file.change)} value={fileKey(file.change)}>
                {file.change.path}
                {file.edited ? " (edited)" : ""}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </div>
      )}

      <section aria-label={selected.change.path} className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2">
          <span className="min-w-0 font-mono text-meta break-all">
            {selected.change.oldPath ? `${selected.change.oldPath} → ` : ""}
            {selected.change.path}
          </span>
          <StatusLabel status={selected.change.status} />
          {selected.edited ? <Badge variant="secondary">Edited</Badge> : null}
          {selected.edited && onDiscard ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="ml-auto"
              onClick={() => {
                onDiscard(selected.change);
                setResets((r) => ({ ...r, [key]: (r[key] ?? 0) + 1 }));
              }}
            >
              <RotateCcwIcon aria-hidden="true" data-icon="inline-start" />
              Discard edits
            </Button>
          ) : null}
        </div>
        {selected.change.reason ? (
          <p className="p-4 text-muted-foreground" data-testid="read-only-reason">
            {READ_ONLY_REASON[selected.change.reason]}
          </p>
        ) : (
          <div className="min-h-80 flex-1" data-testid="diff">
            <DiffBoundary>
              <DiffView
                key={`${key}#${resets[key] ?? 0}`}
                path={`${selected.change.nodeId}/${selected.change.path}`}
                original={selected.original}
                modified={selected.modified}
                readOnly={!editable}
                sideBySide={wide}
                onChange={editable ? (text) => onEdit(selected.change, text) : undefined}
                labels={{
                  original: `${selected.change.path}, before`,
                  modified: editable
                    ? `${selected.change.path}, after (editable)`
                    : `${selected.change.path}, after`,
                }}
              />
            </DiffBoundary>
          </div>
        )}
      </section>
    </div>
  );
}
