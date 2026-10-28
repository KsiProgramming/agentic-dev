"use client";

import { DownloadIcon, FileJsonIcon, FileTextIcon } from "lucide-react";
import { useId, useState } from "react";

import { apiBaseUrl } from "@/api/client";
import { JsonView, parseJson, TextView } from "@/components/json-view";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { MD_UP, useMediaQuery } from "@/lib/use-media-query";
import { AgentMessage } from "@/runs/console/agent-message";
import { isLongOutput } from "@/runs/console/long-output";
import { isFindingsReport, type FindingsReport } from "@/runs/findings/findings";
import { FindingsView } from "@/runs/findings/findings-view";

import { artifactKind, downloadUrl, formatSize, type ArtifactVersion } from "./artifacts";
import { useRunArtifact } from "./use-run-artifacts";

function ArtifactIcon({ artifact }: { artifact: ArtifactVersion }) {
  const Icon = artifactKind(artifact) === "JSON" ? FileJsonIcon : FileTextIcon;
  return <Icon aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />;
}

/** "JSON · 1.2 kB · v2": what kind it is, its size if known, and its version. */
export function artifactFacts(artifact: ArtifactVersion): string {
  const facts = [artifactKind(artifact)];
  if (artifact.size !== null) facts.push(formatSize(artifact.size));
  facts.push(`v${artifact.version}`);
  return facts.join(" · ");
}

/** A Markdown artifact, capped like an agent's answer until "Show full". */
function MarkdownContent({ text }: { text: string }) {
  const [full, setFull] = useState(false);
  const id = useId();
  const long = isLongOutput(text);
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div id={id} className={long && !full ? "max-h-120 overflow-hidden" : undefined}>
        <AgentMessage text={text} />
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
          {full ? "Show less" : "Show full"}
        </Button>
      ) : null}
    </div>
  );
}

/** A findings report (4.4) as findings, with its JSON one toggle away. */
function FindingsArtifact({ report, name }: { report: FindingsReport; name: string }) {
  const [json, setJson] = useState(false);
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="w-fit"
        aria-pressed={json}
        onClick={() => setJson((j) => !j)}
      >
        {json ? "Show findings" : "Show JSON"}
      </Button>
      {json ? (
        <JsonView value={report} label={name} />
      ) : (
        <FindingsView report={report} label={`Findings in ${name}`} />
      )}
    </div>
  );
}

/** An artifact's content, by its kind: a findings report as findings, JSON in `JsonView`, Markdown sanitised (no raw HTML or
 * images), text as text. It is data, never instructions. */
export function ArtifactContent({ artifact, text }: { artifact: ArtifactVersion; text: string }) {
  const kind = artifactKind(artifact);
  if (kind === "JSON") {
    const value = parseJson(text);
    if (isFindingsReport(value)) return <FindingsArtifact report={value} name={artifact.name} />;
    if (value !== undefined) {
      return <JsonView value={value} label={artifact.name} />;
    }
  }
  if (kind === "Markdown") return <MarkdownContent text={text} />;
  return <TextView text={text} label={artifact.name} />;
}

function ArtifactBody({
  runId,
  artifact,
  baseUrl,
}: {
  runId: string;
  artifact: ArtifactVersion;
  baseUrl: string;
}) {
  const query = useRunArtifact(runId, artifact.name, artifact.version, { baseUrl });
  if (query.isPending) return <LoadingState rows={4} label="Loading the artifact…" />;
  if (!query.data) {
    return (
      <ErrorState
        message={query.error?.message ?? "Could not load the artifact."}
        onRetry={() => void query.refetch()}
      />
    );
  }
  return <ArtifactContent artifact={artifact} text={query.data.content} />;
}

/** The sheet that shows one version of an artifact, with Download. */
export function ArtifactSheet({
  runId,
  artifact,
  onClose,
  baseUrl = apiBaseUrl(),
}: {
  runId: string;
  artifact: ArtifactVersion | null;
  onClose: () => void;
  baseUrl?: string;
}) {
  const wide = useMediaQuery(MD_UP);
  return (
    <Sheet open={artifact !== null} onOpenChange={(next) => (next ? null : onClose())}>
      {artifact ? (
        <SheetContent
          side={wide ? "right" : "bottom"}
          data-testid="artifact-sheet"
          className="data-[side=bottom]:max-h-[85svh] data-[side=right]:w-full! data-[side=right]:sm:max-w-[720px]!"
        >
          <SheetHeader className="border-b pr-12">
            <SheetTitle className="font-mono break-all">{artifact.name}</SheetTitle>
            <SheetDescription>
              {artifactFacts(artifact)}
              {artifact.nodeId ? `, written by ${artifact.nodeId}` : ""}
            </SheetDescription>
            <Button asChild variant="outline" size="sm" className="w-fit">
              <a href={downloadUrl(baseUrl, runId, artifact.name, artifact.version)} download>
                <DownloadIcon aria-hidden="true" data-icon="inline-start" />
                Download
              </a>
            </Button>
          </SheetHeader>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
            <ArtifactBody runId={runId} artifact={artifact} baseUrl={baseUrl} />
          </div>
        </SheetContent>
      ) : null}
    </Sheet>
  );
}

/** Artifacts as cards (name in mono, kind, size, version) that open their content in a sheet:
 * those a step wrote or read, or those a gate shows. */
export function ArtifactCards({
  runId,
  artifacts,
  title,
  baseUrl,
}: {
  runId: string;
  artifacts: ArtifactVersion[];
  title: string;
  baseUrl?: string;
}) {
  const [open, setOpen] = useState<ArtifactVersion | null>(null);
  return (
    <section aria-label={title} className="flex flex-col gap-2">
      <h3 className="text-caption font-medium text-muted-foreground">{title}</h3>
      <ul className="grid gap-2 sm:grid-cols-2">
        {artifacts.map((artifact) => (
          <li key={`${artifact.name}@${artifact.version}`} className="min-w-0">
            <button
              type="button"
              data-testid="artifact-card"
              onClick={() => setOpen(artifact)}
              className="flex w-full min-w-0 items-center gap-2 rounded-lg border bg-card px-3 py-2 text-left outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/50"
            >
              <ArtifactIcon artifact={artifact} />
              <span className="flex min-w-0 flex-col">
                <span className="truncate font-mono text-meta">{artifact.name}</span>
                <span className="text-caption text-muted-foreground tabular-nums">
                  {artifactFacts(artifact)}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
      <ArtifactSheet
        runId={runId}
        artifact={open}
        onClose={() => setOpen(null)}
        baseUrl={baseUrl}
      />
    </section>
  );
}
