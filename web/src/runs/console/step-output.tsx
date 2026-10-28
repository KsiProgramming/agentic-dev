"use client";

import { ExternalLinkIcon, FileIcon, InboxIcon } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { Duration } from "@/components/display";
import { OutputView, parseJson } from "@/components/json-view";
import { EmptyState } from "@/components/states";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { MD_UP, useMediaQuery } from "@/lib/use-media-query";

import { ArtifactCards } from "../artifacts/artifact-cards";
import { isFindingsReport } from "../findings/findings";
import { FindingsView } from "../findings/findings-view";
import type { NodeKind } from "../graph/spec-graph";
import type { Step } from "../timeline";
import { AgentMessage } from "./agent-message";
import { GateDecision } from "./gate-decision";
import { isLongOutput } from "./long-output";
import { PortErrors } from "./port-errors";
import { StatusMarker } from "./rail";
import { lastMessage, type StepEntry, type StepRow } from "./step-entries";
import { ErrorLine } from "./step-view";
import { WorkBlock } from "./work-block";
import { agentTurns, mapTotals, workStart } from "./work-blocks";
import { writtenFiles, type WrittenFile } from "./written-files";

export { isLongOutput } from "./long-output";

/** The agent's answer as Markdown, capped when it is long. */
function Answer({ text, streaming }: { text: string; streaming: boolean }) {
  const [full, setFull] = useState(false);
  const id = useId();
  const long = isLongOutput(text);
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div
        id={id}
        data-testid="step-answer"
        data-capped={long && !full ? "true" : undefined}
        className={long && !full ? "max-h-120 overflow-hidden" : undefined}
      >
        <AgentMessage text={text} streaming={streaming} />
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

/** The files the step wrote, as cards that open what was written. */
function WrittenFiles({ files }: { files: WrittenFile[] }) {
  const [open, setOpen] = useState<WrittenFile | null>(null);
  const wide = useMediaQuery(MD_UP);
  return (
    <section aria-label="Files written" className="flex flex-col gap-2">
      <h3 className="text-caption font-medium text-muted-foreground">Files written</h3>
      <ul className="grid gap-2 sm:grid-cols-2">
        {files.map((file) => (
          <li key={file.path} className="min-w-0">
            <button
              type="button"
              data-testid="written-file"
              onClick={() => setOpen(file)}
              className="flex w-full min-w-0 items-center gap-2 rounded-lg border bg-card px-3 py-2 text-left outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/50"
            >
              <FileIcon aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
              <span className="flex min-w-0 flex-col">
                <span className="truncate font-mono text-meta">{file.path}</span>
                <span className="text-caption text-muted-foreground">
                  {file.kind}
                  {file.writes > 1 ? ` · written ${file.writes} times` : ""}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
      <Sheet open={open !== null} onOpenChange={(next) => (next ? null : setOpen(null))}>
        {open ? (
          <SheetContent
            side={wide ? "right" : "bottom"}
            data-testid="written-file-sheet"
            className="data-[side=bottom]:max-h-[85svh] data-[side=right]:w-full! data-[side=right]:sm:max-w-[640px]!"
          >
            <SheetHeader className="border-b pr-12">
              <SheetTitle className="font-mono break-all">{open.path}</SheetTitle>
              <SheetDescription>{open.kind}, as the agent last wrote it</SheetDescription>
            </SheetHeader>
            <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
              {/* Repo content is data: plain text, never Markdown or HTML. */}
              <pre className="font-mono text-xs break-all whitespace-pre-wrap">{open.content}</pre>
            </div>
          </SheetContent>
        ) : null}
      </Sheet>
    </section>
  );
}

/** A container's items, branches or iterations, each selecting its step. */
export function childRows(entries: StepEntry[], row: StepRow): { name: string; row: StepRow }[] {
  const start = entries.findIndex((e) => e.kind === "step" && e.key === row.key);
  const out: { name: string; row: StepRow }[] = [];
  for (let i = start + 1; i < entries.length; i++) {
    const entry = entries[i]!;
    if (entry.depth <= row.depth) break;
    if (entry.depth !== row.depth + 1) continue;
    if (entry.kind === "step") {
      out.push({ name: entry.name, row: entry });
    } else {
      const first = entries.slice(i + 1).find((e): e is StepRow => e.kind === "step");
      if (first) out.push({ name: entry.name, row: first });
    }
  }
  return out;
}

function Children({
  items,
  onSelect,
}: {
  items: { name: string; row: StepRow }[];
  onSelect: (key: string) => void;
}) {
  return (
    <ul className="flex flex-col gap-1" aria-label="Steps inside">
      {items.map(({ name, row }) => (
        <li key={row.key}>
          <button
            type="button"
            onClick={() => onSelect(row.key)}
            className="flex w-full min-w-0 items-center gap-2 rounded-md px-2 py-1.5 text-left outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/50"
          >
            <StatusMarker status={row.step.status} small />
            <span className="min-w-0 truncate font-mono text-meta">{name}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

/** A map's items added up: "3 items · 9 tool calls · 21s". */
function MapTotals({ step }: { step: Step }) {
  const totals = mapTotals(step);
  return (
    <p data-testid="map-totals" className="text-meta text-muted-foreground tabular-nums">
      {totals.items} {totals.items === 1 ? "item" : "items"} · {totals.toolCalls}{" "}
      {totals.toolCalls === 1 ? "tool call" : "tool calls"}
      {totals.ms !== null ? (
        <>
          {" "}
          · <Duration ms={totals.ms} />
        </>
      ) : null}
    </p>
  );
}

function ExternalLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="inline-flex w-fit items-center gap-1 font-mono text-meta break-all text-primary underline-offset-4 hover:underline"
    >
      {children}
      <ExternalLinkIcon aria-hidden="true" className="size-3.5 shrink-0" />
    </a>
  );
}

/**
 * What the step produced: an agent's answer, a tool's result, a gate's decision, a container's
 * items; the pull request or repo it opened, the files and the run artifacts it wrote.
 */
export function StepOutput({
  runId,
  baseUrl,
  step,
  row,
  kind,
  entries,
  extra,
  onSelect,
}: {
  runId: string;
  baseUrl?: string;
  step: Step;
  row: StepRow;
  kind: NodeKind;
  entries: StepEntry[];
  /** E.g. the waiting gate's pointer to the decision. */
  extra?: ReactNode;
  onSelect: (key: string) => void;
}) {
  const message = lastMessage(step);
  const tool = kind === "tool" ? step.turns.findLast((t) => t.kind === "tool") : undefined;
  const files = writtenFiles(step);
  const children = childRows(entries, row);
  const turns = kind === "tool" ? [] : agentTurns(step);
  const final = turns.at(-1);
  const parts: ReactNode[] = [];

  if (step.port) parts.push(<PortErrors key="error" stepId={step.id} port={step.port} />);
  else if (step.error) parts.push(<ErrorLine key="error" error={step.error} />);
  if (step.gate) parts.push(<GateDecision key="gate" gate={step.gate} />);
  if (extra) parts.push(<div key="extra">{extra}</div>);
  if (final && final.work.length > 0) {
    // The work behind the answer, folded: one line above it.
    parts.push(
      <WorkBlock
        key={`work-${final.key}`}
        turn={final}
        startedAt={workStart(step, final, turns.length - 1)}
        live={step.status === "running" && final.answer === null}
      />,
    );
  }
  if (message && message.text.trim()) {
    parts.push(
      <Answer
        key="answer"
        text={message.text}
        streaming={step.status === "running" && !message.final}
      />,
    );
  }
  if (tool?.output != null) {
    const value = parseJson(tool.output);
    parts.push(
      isFindingsReport(value) ? (
        <FindingsView key="tool" report={value} label={`Findings of ${step.id}`} />
      ) : (
        <OutputView key="tool" text={tool.output} label={`Output of ${step.id}`} />
      ),
    );
  }
  if (step.items) parts.push(<MapTotals key="totals" step={step} />);
  if (children.length > 0) {
    parts.push(<Children key="children" items={children} onSelect={onSelect} />);
  }
  if (step.createdRepo) {
    parts.push(
      <p key="repo" className="text-meta text-muted-foreground">
        Created <ExternalLink href={step.createdRepo.url}>{step.createdRepo.fullName}</ExternalLink>
      </p>,
    );
  }
  if (step.prUrl) {
    parts.push(
      <ExternalLink key="pr" href={step.prUrl}>
        {step.prUrl}
      </ExternalLink>,
    );
  }
  if (files.length > 0) parts.push(<WrittenFiles key="files" files={files} />);
  if (step.artifactsWritten.length > 0) {
    parts.push(
      <ArtifactCards
        key="artifacts"
        runId={runId}
        artifacts={step.artifactsWritten}
        title="Artifacts written"
        baseUrl={baseUrl}
      />,
    );
  }

  if (parts.length === 0) {
    return (
      <EmptyState
        icon={InboxIcon}
        message={
          step.status === "running" ? "This step has no output yet." : "This step has no output."
        }
      />
    );
  }
  return <div className="flex min-w-0 flex-col gap-4">{parts}</div>;
}
