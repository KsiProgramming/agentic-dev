"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { fileKey, type FileChange, type FileEdit } from "../gates";

export interface GateEdits {
  /** The edits to send with an approval: one per file whose text differs from what it was. */
  edits: FileEdit[];
  count: number;
  /** The file's text as the approver left it: their edit, else its text at the branch tip. */
  textOf: (change: FileChange) => string;
  isEdited: (change: FileChange) => boolean;
  /** Set the file's new text; text equal to the original is no edit. */
  edit: (change: FileChange, content: string) => void;
  discard: (change: FileChange) => void;
}

/** The approver's edits to a gate's editable files, kept for the open console only. While there
 * are any, leaving the page asks first (`beforeunload`). */
export function useGateEdits(changes: FileChange[]): GateEdits {
  const [contents, setContents] = useState<ReadonlyMap<string, string>>(new Map());

  const editable = useMemo(
    () => new Map(changes.filter((c) => c.editable).map((c) => [fileKey(c), c])),
    [changes],
  );

  const edits = useMemo(
    () =>
      [...contents].flatMap(([key, content]) => {
        const change = editable.get(key);
        return change ? [{ nodeId: change.nodeId, path: change.path, content }] : [];
      }),
    [contents, editable],
  );

  const edit = useCallback((change: FileChange, content: string) => {
    if (!change.editable) return;
    setContents((current) => {
      const key = fileKey(change);
      if (content === change.after) {
        if (!current.has(key)) return current;
        const next = new Map(current);
        next.delete(key);
        return next;
      }
      if (current.get(key) === content) return current;
      return new Map(current).set(key, content);
    });
  }, []);

  const discard = useCallback((change: FileChange) => {
    setContents((current) => {
      const key = fileKey(change);
      if (!current.has(key)) return current;
      const next = new Map(current);
      next.delete(key);
      return next;
    });
  }, []);

  const count = edits.length;
  useEffect(() => {
    if (count === 0) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [count]);

  return {
    edits,
    count,
    textOf: (change) => contents.get(fileKey(change)) ?? change.after ?? "",
    isEdited: (change) => contents.has(fileKey(change)),
    edit,
    discard,
  };
}
