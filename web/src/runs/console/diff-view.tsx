"use client";

import { DiffEditor, loader, type DiffOnMount } from "@monaco-editor/react";
import * as monaco from "monaco-editor/editor/editor.api.js";
// The core editor holds none of these: icons (the diff's +/− markers), the diff's navigation and
// accessible viewer, the usual editing features, and Ctrl+M to move focus out with Tab.
import "monaco-editor/features/codicon/register.js";
import "monaco-editor/features/diffEditor/register.js";
import "monaco-editor/features/find/register.js";
import "monaco-editor/features/clipboard/register.js";
import "monaco-editor/features/contextmenu/register.js";
import "monaco-editor/features/cursorUndo/register.js";
import "monaco-editor/features/wordOperations/register.js";
import "monaco-editor/features/readOnlyMessage/register.js";
import "monaco-editor/features/toggleTabFocusMode/register.js";
import "monaco-editor/languages/definitions/register.all.js";
import { useTheme } from "next-themes";
import { useEffect, useId, useRef, useState } from "react";

// Monaco from the app's own bundle (no CDN), with its editor worker. This module is only loaded
// in the browser, through `next/dynamic`, when a gate's review sheet opens.
self.MonacoEnvironment = {
  getWorker: () =>
    new Worker(new URL("./monaco-worker.ts", import.meta.url), {
      type: "module",
      name: "monaco-editor",
    }),
};
loader.config({ monaco });

export interface DiffViewProps {
  /** Where the file is, for its language and the editors' names. */
  path: string;
  original: string;
  modified: string;
  /** The modified side takes edits; the original side never does. */
  readOnly: boolean;
  sideBySide: boolean;
  onChange?: (text: string) => void;
  /** The accessible names of the two sides. */
  labels: { original: string; modified: string };
}

/** A Monaco diff of one file: what it was on the left (or above, inline) and what it is now. */
export default function DiffView({
  path,
  original,
  modified,
  readOnly,
  sideBySide,
  onChange,
  labels,
}: DiffViewProps) {
  const { resolvedTheme } = useTheme();
  // The editor owns its text once mounted: feeding edits back as `modified` would make
  // @monaco-editor/react reset the model to a stale value while the user types. Remount (a new
  // `key`) to start again from other text.
  const [initial] = useState({ original, modified });
  // Each mount has its own models, so a remount never picks up the text of the last one.
  const instance = useId().replace(/[^A-Za-z0-9]/g, "");
  const changed = useRef(onChange);
  useEffect(() => {
    changed.current = onChange;
  });

  // @monaco-editor/react disposes the models before the diff widget lets go of them, which
  // Monaco reports as an error. It keeps them here (`keepCurrent…Model`); this cleanup, which
  // runs before the library's own, detaches them and then disposes them.
  const diff = useRef<Parameters<DiffOnMount>[0] | null>(null);
  useEffect(
    () => () => {
      const models = diff.current?.getModel();
      diff.current?.setModel(null);
      models?.original.dispose();
      models?.modified.dispose();
    },
    [],
  );

  const onMount: DiffOnMount = (editor) => {
    diff.current = editor;
    const after = editor.getModifiedEditor();
    after.onDidChangeModelContent(() => changed.current?.(after.getValue()));
  };

  return (
    <DiffEditor
      height="100%"
      original={initial.original}
      modified={initial.modified}
      originalModelPath={`inmemory://${instance}/before/${path}`}
      modifiedModelPath={`inmemory://${instance}/after/${path}`}
      keepCurrentOriginalModel
      keepCurrentModifiedModel
      theme={resolvedTheme === "dark" ? "vs-dark" : "light"}
      onMount={onMount}
      loading={null}
      options={{
        renderSideBySide: sideBySide,
        // Inline below 1024 px; Monaco would also switch on its own under 900 px.
        useInlineViewWhenSpaceIsLimited: false,
        readOnly,
        originalEditable: false,
        automaticLayout: true,
        minimap: { enabled: false },
        wordWrap: "on",
        diffWordWrap: "on",
        scrollBeyondLastLine: false,
        renderOverviewRuler: false,
        // Monaco measures text on a canvas, which cannot read `var()`: pass the resolved stack.
        fontFamily: getComputedStyle(document.body).getPropertyValue("--font-mono").trim(),
        fontSize: 13,
        ariaLabel: labels.modified,
        originalAriaLabel: labels.original,
        modifiedAriaLabel: labels.modified,
      }}
    />
  );
}
