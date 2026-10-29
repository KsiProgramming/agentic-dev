"use client";

import { FileDiffIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";

import { fileKey, type FileChange } from "../gates";
import type { GateInfo } from "../timeline";
import type { GateFile } from "./gate-files";
import { GateReviewSheet } from "./gate-review-sheet";

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

/** The files an approval edited, each as a diff of the file as the run wrote it against the
 * approver's text. */
function editedFiles(gate: GateInfo): GateFile[] {
  const shown = new Map(gate.changes.map((c) => [fileKey(c), c]));
  return gate.edits.map((edit) => {
    const change: FileChange = {
      ...(shown.get(fileKey(edit)) ?? {
        nodeId: edit.nodeId,
        path: edit.path,
        oldPath: null,
        status: "modified",
        before: null,
        after: null,
      }),
      editable: true,
      reason: null,
    };
    return { change, original: change.after ?? "", modified: edit.content, edited: true };
  });
}

/** A gate's title and decision in its step: "Approved", "Rejected: why", or "Approved with edits
 * to N files" with a sheet that shows them, read-only. */
export function GateDecision({ gate }: { gate: GateInfo }) {
  const [open, setOpen] = useState(false);
  const edited = gate.decision === "approve" ? gate.edits.length : 0;
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-meta">
      <span className="font-medium">{gate.title}</span>
      {gate.decision ? (
        <span className="text-muted-foreground" data-testid="gate-decision">
          ·{" "}
          {gate.decision !== "approve"
            ? `Rejected${gate.comment ? `: ${gate.comment}` : ""}`
            : `Approved${edited ? ` with edits to ${plural(edited, "file")}` : ""}${
                gate.comment ? `: ${gate.comment}` : ""
              }`}
        </span>
      ) : null}
      {edited > 0 ? (
        <>
          <Button type="button" variant="link" size="sm" onClick={() => setOpen(true)}>
            <FileDiffIcon aria-hidden="true" data-icon="inline-start" />
            View edits
          </Button>
          <GateReviewSheet
            open={open}
            onOpenChange={setOpen}
            title={`Edits at “${gate.title}”`}
            description="What the run wrote on the left, the approved text on the right. The gate committed these edits before the run went on."
            files={open ? editedFiles(gate) : []}
          />
        </>
      ) : null}
    </div>
  );
}
