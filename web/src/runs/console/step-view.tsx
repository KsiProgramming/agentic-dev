"use client";

import { CircleAlertIcon } from "lucide-react";

import type { Step } from "../timeline";
import { AgentTurns } from "./work-block";

export function ErrorLine({ error }: { error: string }) {
  return (
    <p className="flex items-start gap-1.5 text-meta break-words text-destructive">
      <CircleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <span>{error}</span>
    </p>
  );
}

/** What an agent did, in order: each turn's work (reasoning, notes, tool calls) folded into one
 * block, then its answer. */
export function TurnsRail({ step }: { step: Step }) {
  return <AgentTurns step={step} />;
}
