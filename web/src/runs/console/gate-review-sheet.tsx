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
 * which its owner holds.
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
}) {
  const wide = useMediaQuery(LG_UP);
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side={wide ? "right" : "bottom"}
        className="gap-0 data-[side=bottom]:h-svh data-[side=right]:w-[min(1100px,92vw)]! data-[side=right]:max-w-none!"
        data-testid="gate-review"
      >
        <SheetHeader className="border-b pr-12">
          <SheetTitle>{title}</SheetTitle>
          <SheetDescription>{description}</SheetDescription>
        </SheetHeader>
        {notice ? <div className="border-b px-4 py-3">{notice}</div> : null}
        <GateFilesView files={files} wide={wide} onEdit={onEdit} onDiscard={onDiscard} />
        {footer ? (
          <SheetFooter className="mt-0 border-t pb-[max(1rem,env(safe-area-inset-bottom))] md:flex-row md:items-center">
            {footer}
          </SheetFooter>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
