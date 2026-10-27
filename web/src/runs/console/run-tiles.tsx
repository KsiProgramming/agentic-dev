"use client";

import { Duration, Money, StatTile, TokenCount, WaitingTime } from "@/components/display";

import type { CreatedRepo } from "../timeline";
import type { HeaderFacts } from "./run-header";
import { pullRequestNumber, type StepsProgress } from "./run-stats";

/** What the run produced: its pull request, else the repo it created. */
function Output({ prUrl, createdRepo }: { prUrl: string | null; createdRepo: CreatedRepo | null }) {
  if (prUrl) {
    return (
      <StatTile
        label="Output"
        value={
          <a
            href={prUrl}
            target="_blank"
            rel="noreferrer"
            className="text-primary underline-offset-4 hover:underline"
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
  return <StatTile label="Output" value="—" secondary="No pull request" />;
}

function stepsLine(progress: StepsProgress): string | undefined {
  const parts = [];
  if (progress.running > 0) parts.push(`${progress.running} running`);
  if (progress.failed > 0) parts.push(`${progress.failed} failed`);
  return parts.length > 0 ? parts.join(" · ") : undefined;
}

/** The run in five figures under the header: active time (and time waited), cost (against the
 * budget), tokens, steps done and what it produced. */
export function RunTiles({
  facts,
  budget,
  progress,
  createdRepo,
}: {
  facts: HeaderFacts;
  budget: number | null;
  progress: StepsProgress | null;
  createdRepo: CreatedRepo | null;
}) {
  const usage = facts.usage;
  return (
    <section
      aria-label="Run figures"
      className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5"
    >
      <StatTile
        label="Active time"
        value={<Duration data-testid="run-duration" ms={facts.activeMs} />}
        secondary={
          facts.waitingMs > 0 || facts.waitingLive ? (
            <WaitingTime ms={facts.waitingMs} live={facts.waitingLive} />
          ) : undefined
        }
      />
      <StatTile
        label="Cost"
        value={usage ? <Money data-testid="run-cost" usage={usage} /> : "—"}
        secondary={
          budget !== null ? (
            <span data-testid="run-budget">
              of <Money usd={budget} /> budget
            </span>
          ) : (
            "No budget"
          )
        }
      />
      <StatTile
        label="Tokens"
        value={
          usage ? <TokenCount value={usage.inputTokens + usage.outputTokens} usage={usage} /> : "—"
        }
        secondary={
          usage ? (
            <>
              <TokenCount value={usage.inputTokens} label="in" focusable={false} /> ·{" "}
              <TokenCount value={usage.outputTokens} label="out" focusable={false} />
            </>
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
            "—"
          )
        }
        secondary={progress ? stepsLine(progress) : undefined}
      />
      <Output prUrl={facts.prUrl} createdRepo={createdRepo} />
    </section>
  );
}
