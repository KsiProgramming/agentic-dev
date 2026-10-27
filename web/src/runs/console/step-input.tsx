"use client";

import type { ReactNode } from "react";

import { JsonView, OutputView } from "@/components/json-view";
import { LoadingState } from "@/components/states";

import type { SpecNode, WorkflowSpec } from "../graph/spec-graph";
import { allSpecNodes } from "../graph/spec-graph";
import type { StepRow } from "./step-entries";

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

/** What the step was given: its node in the spec, the map item it ran for, and the run's input
 * for the run's first step. */
export function StepInput({
  row,
  spec,
  runInput,
  first,
}: {
  row: StepRow;
  spec: WorkflowSpec | null;
  runInput: string | null;
  /** The run's first step, which gets the run's input. */
  first: boolean;
}) {
  if (!spec) return <LoadingState label="Loading the workflow…" />;
  const node = allSpecNodes(spec).find((n) => n.id === row.step.id);
  return (
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
      {first && runInput ? (
        <Field label="Run input">
          <OutputView text={runInput} label="Run input" />
        </Field>
      ) : null}
      {node ? <NodeFields node={node} /> : null}
    </dl>
  );
}
