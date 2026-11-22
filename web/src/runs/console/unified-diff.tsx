"use client";

import { useId, useState } from "react";

import { TruncatedPath } from "@/components/display";
import { TextView } from "@/components/json-view";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { isLongOutput } from "./long-output";
import { parseRepoDiff, type DiffFileSummary, type DiffLine, type ParsedDiff } from "./parse-diff";

const STATUS_LABEL: Record<DiffFileSummary["status"], string> = {
  added: "Added",
  modified: "Modified",
  deleted: "Deleted",
  renamed: "Renamed",
};

/** The `+` and `−` counts of a file or of the whole change. Colour never stands alone: the sign
 * is in the text. */
function Counts({ added, removed }: { added: number | null; removed: number | null }) {
  if (added === null || removed === null) {
    return <span className="text-muted-foreground">binary</span>;
  }
  return (
    <span className="flex shrink-0 gap-1.5 tabular-nums">
      <span className="text-diff-added">+{added}</span>
      <span className="text-diff-removed">−{removed}</span>
    </span>
  );
}

const ROW: Record<DiffLine["kind"], string> = {
  added: "bg-diff-added-muted",
  removed: "bg-diff-removed-muted",
  context: "",
  hunk: "bg-surface-subtle text-muted-foreground",
  note: "text-muted-foreground italic",
};
const MARKER: Record<DiffLine["kind"], string> = {
  added: "+",
  removed: "−",
  context: " ",
  hunk: " ",
  note: " ",
};

function Row({ line }: { line: DiffLine }) {
  return (
    <div className={cn("flex min-w-max", ROW[line.kind])} data-kind={line.kind}>
      <span
        aria-hidden="true"
        className="w-9 shrink-0 px-1 text-right text-muted-foreground tabular-nums select-none"
      >
        {line.newLine ?? line.oldLine ?? ""}
      </span>
      <span
        className={cn(
          "w-4 shrink-0 text-center select-none",
          line.kind === "added" && "text-diff-added",
          line.kind === "removed" && "text-diff-removed",
        )}
      >
        {/* Screen readers say what a line is; the sign alone is not read as a word. */}
        <span aria-hidden="true">{MARKER[line.kind]}</span>
        {line.kind === "added" || line.kind === "removed" ? (
          <span className="sr-only">{line.kind === "added" ? "Added: " : "Removed: "}</span>
        ) : null}
      </span>
      <span className="pr-3 whitespace-pre text-foreground">{line.text || " "}</span>
    </div>
  );
}

function Files({ parsed }: { parsed: ParsedDiff }) {
  const body = new Map(parsed.sections.map((s) => [s.path, s]));
  return (
    <div className="flex flex-col divide-y divide-divider">
      {parsed.files.map((file) => {
        const section = body.get(file.path);
        return (
          <section key={file.path} aria-label={file.path} className="min-w-0">
            <header className="flex items-center gap-2 bg-surface-subtle px-3 py-1.5 text-caption">
              <span className="shrink-0 text-muted-foreground">{STATUS_LABEL[file.status]}</span>
              <span className="min-w-0 flex-1">
                <TruncatedPath path={file.path} focusable={false} className="text-foreground" />
                {file.oldPath ? (
                  <span className="block truncate text-muted-foreground">
                    from <span className="font-mono">{file.oldPath}</span>
                  </span>
                ) : null}
              </span>
              <Counts added={file.added} removed={file.removed} />
            </header>
            {section && section.lines.length > 0 ? (
              <div className="overflow-x-auto py-1 font-mono text-caption">
                {section.lines.map((line, i) => (
                  <Row key={i} line={line} />
                ))}
              </div>
            ) : null}
          </section>
        );
      })}
    </div>
  );
}

/**
 * A `repo.diff` result as a unified diff: a header line with the totals, then each file with its
 * header on `surface-subtle` and its changed lines, with a `+` or `−` marker in the gutter and a
 * tinted fill (`diff-*` tokens). It scrolls in its own box and is capped with "Show full output"
 * when long. A result that is not a diff (an error, a refusal) is shown as plain text. The text
 * is repo content: always rendered as text.
 */
export function UnifiedDiff({ text, label }: { text: string; label: string }) {
  const parsed = parseRepoDiff(text);
  const [full, setFull] = useState(false);
  const id = useId();
  if (parsed === null) return <TextView text={text} label={label} />;
  const long = isLongOutput(text);
  const added = parsed.files.reduce((n, f) => n + (f.added ?? 0), 0);
  const removed = parsed.files.reduce((n, f) => n + (f.removed ?? 0), 0);
  return (
    <div data-slot="unified-diff" className="flex min-w-0 flex-col gap-2">
      <div className="min-w-0 rounded-md border">
        <p className="flex flex-wrap items-center gap-x-2 border-b px-3 py-2 text-caption text-foreground-secondary">
          <span className="min-w-0">{parsed.summary.replace(/ \(\+\d+ -\d+\)/, "")}</span>
          <Counts added={added} removed={removed} />
        </p>
        <div
          id={id}
          role="group"
          aria-label={label}
          data-capped={long && !full ? "true" : undefined}
          className={cn("overflow-y-auto", long && !full ? "max-h-96" : undefined)}
        >
          <Files parsed={parsed} />
        </div>
        {parsed.truncated ? (
          <p className="border-t px-3 py-2 text-caption text-foreground-secondary">
            {parsed.truncated.charAt(0).toUpperCase() + parsed.truncated.slice(1)}.
          </p>
        ) : null}
      </div>
      {long ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="w-fit"
          aria-expanded={full}
          aria-controls={id}
          onClick={() => setFull((f) => !f)}
        >
          {full ? "Show less" : "Show full output"}
        </Button>
      ) : null}
    </div>
  );
}
