"use client";

import type { ReactNode } from "react";

import type { components } from "@/api/schema";
import { JsonView, OutputView } from "@/components/json-view";
import { LoadingState } from "@/components/states";

import { ArtifactCards } from "../artifacts/artifact-cards";
import type { SpecNode, WorkflowSpec } from "../graph/spec-graph";
import { allSpecNodes } from "../graph/spec-graph";
import { repoLabel } from "../summaries";
import { AgentMessage } from "./agent-message";
import type { StepRow } from "./step-entries";

type IssueBrief = components["schemas"]["IssueBrief"];

/** What the platform tells every agent of the run (`RunContext`, 6.8, 6.9, 7.4). */
export interface RunContextView {
  repoUrl: string | null;
  request: string | null;
  issue: IssueBrief | null;
}

/** The Jira issue as its agents read it, the same fields in the same order (`IssueBrief.text`). */
export function issueBriefMarkdown(issue: IssueBrief): string {
  const lines = [`# ${issue.key}: ${issue.summary}`.trimEnd(), "", `- URL: ${issue.url}`];
  lines.push(`- Project: ${issue.project}`);
  if (issue.type) lines.push(`- Type: ${issue.type}`);
  if (issue.status) lines.push(`- Status: ${issue.status}`);
  if (issue.labels && issue.labels.length > 0) lines.push(`- Labels: ${issue.labels.join(", ")}`);
  if (issue.components && issue.components.length > 0) {
    lines.push(`- Components: ${issue.components.join(", ")}`);
  }
  if (issue.story_points !== null && issue.story_points !== undefined) {
    lines.push(`- Story points: ${issue.story_points}`);
  }
  const criteria = issue.acceptance_criteria?.trim();
  lines.push("", criteria ? `## Acceptance criteria\n\n${criteria}` : "Acceptance criteria: none.");
  const description = issue.description?.trim();
  if (description) lines.push("", `## Description\n\n${description}`);
  return lines.join("\n");
}

/** The run's context as every agent was told it: the repo, the request and, for a run Jira
 * started, the issue. Issue text is Jira's: sanitised Markdown, no HTML or images. */
function RunContextFields({
  context,
  sameAsInput,
}: {
  context: RunContextView;
  /** The request is the run input shown above (the first step): said, not repeated. */
  sameAsInput: boolean;
}) {
  if (!context.repoUrl && !context.request && !context.issue) return null;
  return (
    <section aria-labelledby="run-context-title" className="flex min-w-0 flex-col gap-3">
      <h3 id="run-context-title" className="text-section font-medium text-foreground">
        Run context
      </h3>
      <p className="text-meta text-foreground-secondary">
        Every agent of the run is told this after its instructions.
      </p>
      <dl className="flex min-w-0 flex-col gap-4">
        {context.repoUrl ? (
          <Field label="Repository">
            <Mono>{repoLabel(context.repoUrl)}</Mono>
          </Field>
        ) : null}
        {context.request ? (
          <Field label="Request">
            {sameAsInput ? (
              <span className="text-foreground-secondary">The run input above.</span>
            ) : (
              <OutputView text={context.request} label="Request" />
            )}
          </Field>
        ) : null}
        {context.issue ? (
          <Field label="Jira issue">
            <div
              className="rounded-lg border bg-surface-subtle p-3"
              data-testid="run-context-issue"
            >
              <AgentMessage text={issueBriefMarkdown(context.issue)} />
            </div>
          </Field>
        ) : null}
      </dl>
    </section>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <dt className="text-caption text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-body">{children}</dd>
    </div>
  );
}

function Mono({ children }: { children: ReactNode }) {
  return <span className="font-mono text-meta break-all">{children}</span>;
}

/** What the spec gave the node: an agent's role, instructions, model and tools; a tool's
 * arguments; a gate's title; a container's settings. Text only: the spec is user content. */
function NodeFields({ node }: { node: SpecNode }) {
  switch (node.type) {
    case "agent":
      return (
        <>
          <Field label="Role">{node.role}</Field>
          <Field label="Instructions">
            <p className="max-w-prose break-words whitespace-pre-wrap">{node.instructions}</p>
          </Field>
          <Field label="Model">
            {node.model ? <Mono>{node.model}</Mono> : "Workspace default"}
          </Field>
          <Field label="Tools">
            {node.tools && node.tools.length > 0 ? (
              <ul className="flex flex-wrap gap-1.5">
                {node.tools.map((tool) => (
                  <li key={tool} className="rounded-sm border px-1.5 py-0.5">
                    <Mono>{tool}</Mono>
                  </li>
                ))}
              </ul>
            ) : (
              "None"
            )}
          </Field>
        </>
      );
    case "tool":
      return (
        <>
          <Field label="Tool">
            <Mono>{node.tool}</Mono>
          </Field>
          {node.args && Object.keys(node.args).length > 0 ? (
            <Field label="Arguments">
              <JsonView value={node.args} label={`Arguments of ${node.id}`} />
            </Field>
          ) : null}
        </>
      );
    case "gate":
      return (
        <>
          <Field label="Title">{node.title}</Field>
          {node.prompt ? <Field label="Prompt">{node.prompt}</Field> : null}
        </>
      );
    case "map":
      return (
        <>
          <Field label="Over">
            <Mono>{node.over}</Mono>
          </Field>
          <Field label="At most at once">{node.max_concurrency}</Field>
        </>
      );
    case "loop":
      return (
        <>
          <Field label="Until">
            <Mono>{node.until}</Mono>
          </Field>
          <Field label="At most">{node.max_iterations} iterations</Field>
        </>
      );
    case "parallel":
      return (
        <Field label="Join">
          <Mono>{node.join}</Mono>
        </Field>
      );
    case "orchestrator":
      return (
        <>
          <Field label="Hub role">{node.hub.role}</Field>
          <Field label="Hub instructions">
            <p className="max-w-prose break-words whitespace-pre-wrap">{node.hub.instructions}</p>
          </Field>
          <Field label="Hub model">
            {node.hub.model ? <Mono>{node.hub.model}</Mono> : "Workspace default"}
          </Field>
          <Field label="At most">
            {node.max_workers} tasks, {node.max_concurrency} at once
          </Field>
          <Field label="Replan">
            {node.replan
              ? `On failure, up to ${node.replan.max_rounds} ${node.replan.max_rounds === 1 ? "time" : "times"}`
              : "Off: a failed task fails the orchestrator"}
          </Field>
        </>
      );
    case "subflow":
      return (
        <>
          <Field label="Calls">
            <Mono>{node.workflow.id}</Mono> · version {node.workflow.version}
          </Field>
          <Field label="Input">
            {node.input ? <Mono>{node.input}</Mono> : "The subflow's input, unchanged"}
          </Field>
        </>
      );
    case "reduce":
      return (
        <>
          <Field label="Reduces">
            <Mono>{node.from}</Mono>
          </Field>
          <Field label="Strategy">
            <Mono>{node.strategy}</Mono>
          </Field>
        </>
      );
    default:
      return null;
  }
}

/** The JSON Schemas a typed agent or tool node (4.2) checks its input and output against. */
function PortSchemas({ node }: { node: SpecNode }) {
  if (node.type !== "agent" && node.type !== "tool") return null;
  return (
    <>
      {node.input_schema ? (
        <Field label="Input schema">
          <JsonView value={node.input_schema} label={`Input schema of ${node.id}`} />
        </Field>
      ) : null}
      {node.output_schema ? (
        <Field label="Output schema">
          <JsonView value={node.output_schema} label={`Output schema of ${node.id}`} />
        </Field>
      ) : null}
    </>
  );
}

/** The run artifacts (4.3) the node's spec says it reads and writes. */
function ArtifactFields({ node }: { node: SpecNode }) {
  const reads = node.type === "agent" || node.type === "tool" ? (node.reads ?? []) : [];
  const writes =
    node.type === "agent" || node.type === "tool" || node.type === "reduce" ? node.writes : null;
  return (
    <>
      {reads.length > 0 ? (
        <Field label="Reads">
          <ul className="flex flex-wrap gap-1.5">
            {reads.map((name) => (
              <li key={name} className="rounded-sm border px-1.5 py-0.5">
                <Mono>{name}</Mono>
              </li>
            ))}
          </ul>
        </Field>
      ) : null}
      {writes ? (
        <Field label="Writes">
          <Mono>{writes}</Mono>
        </Field>
      ) : null}
    </>
  );
}

/** What the step was given: the run artifacts it read, its node in the spec, the map item or
 * orchestrator task it ran for, and the run's input for the run's first step. */
export function StepInput({
  runId,
  baseUrl,
  row,
  spec,
  runInput,
  first,
  runContext = null,
}: {
  runId: string;
  baseUrl?: string;
  row: StepRow;
  spec: WorkflowSpec | null;
  runInput: string | null;
  /** The run's first step, which gets the run's input. */
  first: boolean;
  /** What every agent is told; shown on agent steps. */
  runContext?: RunContextView | null;
}) {
  if (!spec) return <LoadingState label="Loading the workflow…" />;
  const node = allSpecNodes(spec).find((n) => n.id === row.step.id);
  const read = row.step.artifactsRead;
  return (
    <div className="flex min-w-0 flex-col gap-4">
      {read.length > 0 ? (
        <ArtifactCards runId={runId} artifacts={read} title="Artifacts read" baseUrl={baseUrl} />
      ) : null}
      <dl className="flex min-w-0 flex-col gap-4">
        {row.item ? (
          <Field label="Item">
            {typeof row.item.item === "string" ? (
              <Mono>{row.item.item}</Mono>
            ) : (
              <JsonView value={row.item.item} label={`Item ${row.item.index + 1}`} />
            )}
          </Field>
        ) : null}
        {row.iteration ? <Field label="Iteration">{row.iteration.index}</Field> : null}
        {row.task ? (
          <Field label="Task">
            {/* The hub's words reach the worker as data: shown as text. */}
            <span className="flex min-w-0 flex-wrap items-baseline gap-x-2">
              <Mono>{row.task.id}</Mono>
              <span>{row.task.title}</span>
              {row.task.round > 1 ? (
                <span className="text-meta text-foreground-secondary">round {row.task.round}</span>
              ) : null}
            </span>
          </Field>
        ) : null}
        {first && runInput ? (
          <Field label="Run input">
            <OutputView text={runInput} label="Run input" />
          </Field>
        ) : null}
        {node ? <NodeFields node={node} /> : null}
        {node ? <ArtifactFields node={node} /> : null}
        {node ? <PortSchemas node={node} /> : null}
      </dl>
      {node?.type === "agent" && runContext ? (
        <RunContextFields
          context={runContext}
          sameAsInput={first && runInput !== null && runInput === runContext.request}
        />
      ) : null}
    </div>
  );
}
