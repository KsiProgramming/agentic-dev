"use client";

import { ActivityIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Duration, Money, WaitingTime } from "@/components/display";
import { EmptyState } from "@/components/states";
import { StatusBadge } from "@/components/status-badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { kindLabel } from "../graph/graph-nodes";
import type { NodeKind, WorkflowSpec } from "../graph/spec-graph";
import { stepUsage } from "../timeline";
import type { ReceivedRunEvent } from "../types";
import { RawEvents } from "./raw-events";
import { stepBadge } from "./step-status";
import type { StepEntry, StepRow } from "./step-entries";
import { StepInput } from "./step-input";
import { elapsedMs } from "./step-list";
import { childRows, StepOutput } from "./step-output";
import { StepUsage } from "./step-usage";
import { TurnsRail } from "./step-view";

export type StepTab = "output" | "activity" | "input" | "usage" | "events";

export const STEP_TABS: readonly StepTab[] = ["output", "activity", "input", "usage", "events"];

const LABELS: Record<StepTab, string> = {
  output: "Output",
  activity: "Activity",
  input: "Input",
  usage: "Usage",
  events: "Events",
};

/** The selected step: its name, status, time and cost, then its Output, Activity, Input, Usage
 * and Events. */
export function StepPanel({
  row,
  kind,
  entries,
  spec,
  runInput,
  first,
  events,
  now,
  tab,
  onTab,
  onSelect,
  extra,
}: {
  row: StepRow;
  kind: NodeKind;
  entries: StepEntry[];
  spec: WorkflowSpec | null;
  runInput: string | null;
  first: boolean;
  events: ReceivedRunEvent[];
  now: number;
  tab: StepTab;
  onTab: (tab: StepTab) => void;
  onSelect: (key: string) => void;
  extra?: ReactNode;
}) {
  const { step } = row;
  const usage = stepUsage(step);
  const ms = elapsedMs(step.startedAt, step.endedAt, now);
  const badge = stepBadge(step.status);
  const children = childRows(entries, row);
  return (
    <section
      aria-labelledby="step-panel-title"
      data-testid="step-panel"
      data-key={row.key}
      className="flex min-w-0 flex-col gap-3 rounded-lg border bg-card p-4"
    >
      <header className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5">
        <h2
          id="step-panel-title"
          className="min-w-0 font-mono text-section font-semibold break-all"
        >
          {row.name}
        </h2>
        <StatusBadge status={badge.status} label={badge.label} />
        <span className="text-meta text-muted-foreground">
          {kindLabel(kind)}
          {row.name !== step.id ? (
            <>
              {" "}
              <span className="font-mono">{step.id}</span>
            </>
          ) : null}
        </span>
        <span className="ml-auto flex items-center gap-3 text-meta text-muted-foreground">
          {step.gate ? (
            <WaitingTime ms={ms} live={step.status === "waiting"} />
          ) : (
            <Duration ms={ms} />
          )}
          {usage ? <Money usage={usage} /> : null}
        </span>
      </header>
      <Tabs value={tab} onValueChange={(next) => onTab(next as StepTab)}>
        <TabsList aria-label="Step views" className="max-w-full overflow-x-auto">
          {STEP_TABS.map((t) => (
            <TabsTrigger key={t} value={t}>
              {LABELS[t]}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="output" className="pt-3">
          <StepOutput
            step={step}
            row={row}
            kind={kind}
            entries={entries}
            extra={extra}
            onSelect={onSelect}
          />
        </TabsContent>
        <TabsContent value="activity" className="pt-3">
          {step.turns.length > 0 ? (
            <TurnsRail step={step} />
          ) : (
            <EmptyState icon={ActivityIcon} message="This step made no tool calls." />
          )}
        </TabsContent>
        <TabsContent value="input" className="pt-3">
          <StepInput row={row} spec={spec} runInput={runInput} first={first} />
        </TabsContent>
        <TabsContent value="usage" className="pt-3">
          <StepUsage step={step} items={children} />
        </TabsContent>
        <TabsContent value="events" className="pt-3">
          <RawEvents key={step.id} events={events} node={step.id} />
        </TabsContent>
      </Tabs>
    </section>
  );
}
