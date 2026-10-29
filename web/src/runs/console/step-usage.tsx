"use client";

import { CoinsIcon } from "lucide-react";

import { Money, StatStrip, StatTile, TokenCount } from "@/components/display";
import { EmptyState } from "@/components/states";

import { stepUsage, type Step } from "../timeline";
import type { StepRow } from "./step-entries";

/** The tokens and cost of the step; a container's total, then each of its steps. */
export function StepUsage({
  step,
  items,
}: {
  step: Step;
  /** A container's steps, from `childRows`. */
  items: { name: string; row: StepRow }[];
}) {
  const usage = stepUsage(step);
  if (!usage) return <EmptyState icon={CoinsIcon} message="This step used no model." />;
  const parts = items
    .map(({ name, row }) => ({ name, key: row.key, usage: stepUsage(row.step) }))
    .filter((c) => c.usage !== null);
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <StatStrip columns={4}>
        <StatTile label="Input" value={<TokenCount value={usage.inputTokens} usage={usage} />} />
        <StatTile label="Output" value={<TokenCount value={usage.outputTokens} usage={usage} />} />
        <StatTile
          label="Cache"
          value={
            <TokenCount value={usage.cacheReadTokens + usage.cacheWriteTokens} usage={usage} />
          }
          secondary={
            <>
              <TokenCount value={usage.cacheReadTokens} label="read" focusable={false} /> ·{" "}
              <TokenCount value={usage.cacheWriteTokens} label="written" focusable={false} />
            </>
          }
        />
        <StatTile label="Cost" value={<Money data-testid="step-cost" usage={usage} />} />
      </StatStrip>
      {parts.length > 0 ? (
        <ul
          aria-label="Usage by step"
          className="flex flex-col divide-y divide-divider rounded-lg border"
        >
          {parts.map((part) => (
            <li key={part.key} className="flex min-w-0 items-center gap-3 px-3 py-2 text-meta">
              <span className="min-w-0 flex-1 truncate font-mono">{part.name}</span>
              <TokenCount
                value={part.usage!.inputTokens + part.usage!.outputTokens}
                label="tokens"
                usage={part.usage!}
                focusable={false}
                className="text-muted-foreground"
              />
              <Money usage={part.usage!} focusable={false} />
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
