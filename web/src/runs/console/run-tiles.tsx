"use client";

import { useState } from "react";

import {
  Duration,
  Money,
  StatStrip,
  StatTile,
  TokenCount,
  WaitingTime,
} from "@/components/display";

import { ArtifactSheet, artifactFacts } from "../artifacts/artifact-cards";
import type { ArtifactVersion } from "../artifacts/artifacts";
import { versionOf } from "../artifacts/artifacts-view";
import { useRunArtifacts } from "../artifacts/use-run-artifacts";
import type { CreatedRepo } from "../timeline";
import type { HeaderFacts } from "./run-header";
import { pullRequestNumber, type StepsProgress } from "./run-stats";

/** What the run produced: its pull request, else the repo it created, else the artifact it wrote
 * last (a report-only run's result), which opens in its sheet. Never an empty tile
 * (design-language.md → Content rules). */
function Output({
  prUrl,
  createdRepo,
  runId,
  written,
  baseUrl,
}: {
  prUrl: string | null;
  createdRepo: CreatedRepo | null;
  runId: string;
  written: number;
  baseUrl?: string;
}) {
  const artifacts = useRunArtifacts(runId, written, baseUrl);
  const [open, setOpen] = useState<ArtifactVersion | null>(null);
  if (prUrl) {
    return (
      <StatTile
        label="Output"
        value={
          <a
            href={prUrl}
            target="_blank"
            rel="noreferrer"
            className="text-foreground underline-offset-4 hover:underline"
          >
            PR {pullRequestNumber(prUrl)}
          </a>
        }
        secondary="Opened"
      />
    );
  }
  if (createdRepo) {
    return (
      <StatTile
        label="Output"
        value={<span className="font-mono text-section">{createdRepo.fullName}</span>}
        secondary="Repo created"
      />
    );
  }
  const last = [...(Array.isArray(artifacts.data) ? artifacts.data : [])].sort((a, b) =>
    b.created_at.localeCompare(a.created_at),
  )[0];
  if (last) {
    const version = versionOf(last);
    return (
      <>
        <StatTile
          label="Output"
          value={
            <button
              type="button"
              data-testid="run-output-artifact"
              onClick={() => setOpen(version)}
              className="max-w-full truncate rounded-sm font-mono text-section underline-offset-4 hover:underline"
            >
              {last.name}
            </button>
          }
          secondary={artifactFacts(version)}
        />
        <ArtifactSheet
          runId={runId}
          artifact={open}
          onClose={() => setOpen(null)}
          baseUrl={baseUrl}
        />
      </>
    );
  }
  return (
    <StatTile
      label="Output"
      value={<span className="text-placeholder">None</span>}
      secondary="This run wrote nothing yet"
    />
  );
}

function stepsLine(progress: StepsProgress): string | undefined {
  const parts = [];
  if (progress.running > 0) parts.push(`${progress.running} running`);
  if (progress.failed > 0) parts.push(`${progress.failed} failed`);
  return parts.length > 0 ? parts.join(" · ") : undefined;
}

/** The run in five figures under the header, as one strip: active time (and time waited), cost
 * (against the budget), tokens, steps done and what it produced. A run that called no model
 * says so instead of showing "—". */
export function RunTiles({
  facts,
  budget,
  progress,
  createdRepo,
  runId,
  written,
  noModelCalls,
  baseUrl,
}: {
  facts: HeaderFacts;
  budget: number | null;
  progress: StepsProgress | null;
  createdRepo: CreatedRepo | null;
  runId: string;
  /** How many `artifact_written` events the page has, so the Output tile follows the run. */
  written: number;
  noModelCalls: boolean;
  baseUrl?: string;
}) {
  const usage = facts.usage;
  const dash = <span className="text-placeholder">—</span>;
  return (
    <section aria-label="Run figures">
      <StatStrip columns={5}>
        <StatTile
          label="Active time"
          value={<Duration data-testid="run-duration" ms={facts.activeMs} />}
          secondary={
            facts.waitingMs > 0 || facts.waitingLive ? (
              <WaitingTime
                ms={facts.waitingMs}
                live={facts.waitingLive}
                className="text-status-waiting"
              />
            ) : undefined
          }
        />
        <StatTile
          label="Cost"
          value={
            usage ? (
              <Money data-testid="run-cost" usage={usage} />
            ) : noModelCalls ? (
              <Money data-testid="run-cost" usd={0} />
            ) : (
              dash
            )
          }
          secondary={
            budget !== null ? (
              <span data-testid="run-budget">
                of <Money usd={budget} /> budget
              </span>
            ) : noModelCalls ? (
              "No model calls"
            ) : (
              "No budget"
            )
          }
        />
        <StatTile
          label="Tokens"
          value={
            usage ? (
              <TokenCount value={usage.inputTokens + usage.outputTokens} usage={usage} />
            ) : noModelCalls ? (
              "None"
            ) : (
              dash
            )
          }
          secondary={
            usage ? (
              <>
                <TokenCount value={usage.inputTokens} label="in" focusable={false} /> ·{" "}
                <TokenCount value={usage.outputTokens} label="out" focusable={false} />
              </>
            ) : noModelCalls ? (
              "No agents ran"
            ) : undefined
          }
        />
        <StatTile
          label="Steps"
          value={
            progress ? (
              <span data-testid="run-steps">
                {progress.done} of {progress.total}
              </span>
            ) : (
              dash
            )
          }
          secondary={progress ? stepsLine(progress) : undefined}
        />
        <Output
          prUrl={facts.prUrl}
          createdRepo={createdRepo}
          runId={runId}
          written={written}
          baseUrl={baseUrl}
        />
      </StatStrip>
    </section>
  );
}
