"use client";

import { CheckIcon, CopyIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** `text` parsed as JSON if it is a JSON object or array; otherwise `undefined`. */
export function parseJson(text: string): unknown {
  const trimmed = text.trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return undefined;
  try {
    return JSON.parse(trimmed) as unknown;
  } catch {
    return undefined;
  }
}

function Scalar({ value }: { value: unknown }) {
  if (typeof value === "string") {
    return (
      <span className="break-all whitespace-pre-wrap text-foreground">{JSON.stringify(value)}</span>
    );
  }
  return (
    <span className="text-foreground">
      {value === undefined ? "undefined" : JSON.stringify(value)}
    </span>
  );
}

function Node({
  name,
  value,
  depth,
  openDepth,
}: {
  name: string | null;
  value: unknown;
  depth: number;
  openDepth: number;
}) {
  const label = name === null ? null : <span className="text-muted-foreground">{name}: </span>;
  if (value === null || typeof value !== "object") {
    return (
      <div className="pl-4">
        {label}
        <Scalar value={value} />
      </div>
    );
  }
  const entries = Array.isArray(value)
    ? value.map((v, i) => [String(i), v] as const)
    : Object.entries(value as Record<string, unknown>);
  const [open, close] = Array.isArray(value) ? ["[", "]"] : ["{", "}"];
  if (entries.length === 0) {
    return (
      <div className="pl-4">
        {label}
        {open}
        {close}
      </div>
    );
  }
  return (
    <details open={depth < openDepth} className="group pl-4">
      <summary className="-ml-4 cursor-pointer list-none rounded-sm pl-4 outline-none marker:hidden hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/50">
        <span
          aria-hidden="true"
          className="-ml-3.5 inline-block w-3 text-muted-foreground group-open:rotate-90 motion-safe:transition-transform"
        >
          ›
        </span>
        {label}
        {open}
        <span className="text-muted-foreground group-open:hidden">
          {" "}
          {entries.length} {entries.length === 1 ? "entry" : "entries"} {close}
        </span>
      </summary>
      {entries.map(([key, child]) => (
        <Node key={key} name={key} value={child} depth={depth + 1} openDepth={openDepth} />
      ))}
      <div>{close}</div>
    </details>
  );
}

/**
 * A JSON value, pretty-printed and collapsible: levels past `openDepth` start collapsed. Wide
 * content scrolls inside its own box. Values are shown as text, never as HTML.
 */
export function JsonView({
  value,
  label = "JSON",
  openDepth = 2,
  className,
}: {
  value: unknown;
  label?: string;
  openDepth?: number;
  className?: string;
}) {
  return (
    <div
      data-slot="json-view"
      className={cn(
        "relative rounded-md border bg-surface-subtle font-mono text-caption",
        className,
      )}
    >
      <CopyButton text={JSON.stringify(value, null, 2)} label={`Copy ${label}`} />
      <div role="group" aria-label={label} className="-ml-2 max-h-96 overflow-auto py-2 pr-10">
        <Node name={null} value={value} depth={0} openDepth={openDepth} />
      </div>
    </div>
  );
}

/** Text that is not JSON (e.g. a tool's plain output), in the same box. */
export function TextView({
  text,
  label,
  className,
}: {
  text: string;
  label: string;
  className?: string;
}) {
  return (
    <div
      data-slot="text-view"
      className={cn(
        "relative rounded-md border bg-surface-subtle font-mono text-caption",
        className,
      )}
    >
      <CopyButton text={text} label={`Copy ${label}`} />
      <pre
        aria-label={label}
        className="max-h-96 overflow-auto p-2 pr-10 break-all whitespace-pre-wrap"
      >
        {text}
      </pre>
    </div>
  );
}

/** A tool's output: as JSON if it parses, as plain text otherwise. */
export function OutputView({ text, label }: { text: string; label: string }) {
  const json = parseJson(text);
  return json === undefined ? (
    <TextView text={text} label={label} />
  ) : (
    <JsonView value={json} label={label} />
  );
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-xs"
      aria-label={label}
      className="absolute top-1 right-1"
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
    >
      {copied ? <CheckIcon aria-hidden="true" /> : <CopyIcon aria-hidden="true" />}
    </Button>
  );
}
