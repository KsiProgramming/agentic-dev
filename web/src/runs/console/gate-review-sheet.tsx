"use client";

import type { ReactNode } from "react";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { LG_UP, useMediaQuery } from "@/lib/use-media-query";

import type { FileChange } from "../gates";
import { GateFilesView, type GateFile } from "./gate-files";

/**
 * The wide sheet with a gate's changed files (tech-stack → Review sheet): a side sheet of
 * `min(1100px, 92vw)` from 1024 px, a full-height bottom sheet below. Closing it keeps the edits,
 * which its owner holds. Without `onEdit` it is read-only, as for a writer's saved changes (12.3);
 * `body` takes the files' place while there are none to show (loading, empty, error).
 */
export function GateReviewSheet({
  open,
  onOpenChange,
  title,
  description,
  files,
  onEdit,
  onDiscard,
  notice,
  footer,
  body,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  files: GateFile[];
  onEdit?: (change: FileChange, text: string) => void;
  onDiscard?: (change: FileChange) => void;
  /** Shown above the files, e.g. why a decision was refused. */
  notice?: ReactNode;
  footer?: ReactNode;
  body?: ReactNode;
}) {
  const wide = useMediaQuery(LG_UP);
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side={wide ? "right" : "bottom"}
        className="gap-0 data-[side=bottom]:h-svh data-[side=right]:w-[min(1100px,92vw)]! data-[side=right]:max-w-none!"
        data-testid="gate-review"
      >
        <SheetHeader>
          <SheetTitle>{title}</SheetTitle>
          <SheetDescription>{description}</SheetDescription>
        </SheetHeader>
        {notice ? <div className="border-b px-4 py-3">{notice}</div> : null}
        {body ?? (
          // Remounted per file set, so the first file is selected again.
          <GateFilesView
            key={files.map((f) => `${f.change.nodeId}:${f.change.path}`).join("|")}
            files={files}
            wide={wide}
            onEdit={onEdit}
            onDiscard={onDiscard}
          />
        )}
        {footer ? (
          <SheetFooter className="mt-0 pb-[max(1rem,env(safe-area-inset-bottom))] md:flex-row md:items-center">
            {footer}
          </SheetFooter>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
