"use client";

import Form, { type IChangeEvent } from "@rjsf/core";
import type { RJSFSchema, UiSchema } from "@rjsf/utils";
import validator from "@rjsf/validator-ajv8";
import { CircleAlertIcon, SlidersHorizontalIcon, XIcon } from "lucide-react";
import { useState } from "react";

import { JsonView } from "@/components/json-view";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { isKnownKind, KindIcon, kindLabel } from "@/runs/graph/node-kinds";
import type { NodeKind, SpecNode, WorkflowSpec } from "@/runs/graph/spec-graph";

import type { ValueChange } from "./diff";
import type { Edit } from "./edits";
import { formDefaults } from "./form/theme";
import type { BuilderFormContext } from "./form/workflow-ref-field";
import { ManifestIcon, type NodeManifest } from "./node-types";
import { ValueChanges } from "./history";
import { documentParams, nodeParams, paramEdit, sameParams, type Schema } from "./params";

/**
 * The builder's side panel (5.4): the selected node's parameters as a form drawn from its
 * manifest (`parameters` and `ui`), or the workflow's own fields when no node is selected. Every
 * change the form accepts becomes a `setParam` edit in the builder's buffer; a value the schema
 * refuses is shown on its field and kept out of the spec.
 */

type Json = Record<string, unknown>;

/** Applied to every manifest's `ui`: list items are removed, never copied or reordered. */
const GLOBAL_UI = { "ui:globalOptions": { orderable: false, copyable: false } };

/**
 * A form over `values`, which are the spec's: each accepted change goes to `onChange` as the
 * whole new value. A change from outside (undo, Discard, a rebase) starts the form again from it.
 */
function ParamForm({
  idPrefix,
  schema,
  ui,
  values,
  readOnly = false,
  context,
  onChange,
}: {
  idPrefix: string;
  schema: Schema;
  ui: UiSchema;
  values: Json;
  /** An older version (5.7): shown, not edited. */
  readOnly?: boolean;
  /** Where the form is, for fields that look things up (a subflow's workflow, 6.5). */
  context?: BuilderFormContext;
  onChange: (next: Json) => void;
}) {
  const [draft, setDraft] = useState(values);
  const [seen, setSeen] = useState(values);
  const [epoch, setEpoch] = useState(0);
  if (!sameParams(values, seen)) {
    setSeen(values);
    if (!sameParams(values, draft)) {
      setDraft(values);
      setEpoch((e) => e + 1);
    }
  }

  return (
    <Form
      key={epoch}
      {...formDefaults}
      idPrefix={idPrefix}
      schema={schema as RJSFSchema}
      uiSchema={{ ...GLOBAL_UI, ...ui }}
      formData={draft}
      readonly={readOnly}
      formContext={context}
      validator={validator}
      className="flex flex-col gap-4"
      onChange={(event: IChangeEvent<Json>) => {
        const next = event.formData ?? {};
        setDraft(next);
        if (event.errors.length === 0) onChange(next);
      }}
    />
  );
}

function PanelHeader({
  icon,
  title,
  aside,
  description,
  onClose,
}: {
  icon: React.ReactNode;
  title: string;
  aside?: React.ReactNode;
  description?: string;
  onClose?: () => void;
}) {
  return (
    <div className="flex items-start gap-2 border-b bg-surface-subtle px-4 py-3">
      <span className="mt-1 shrink-0 text-muted-foreground">{icon}</span>
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <h2 className="flex min-w-0 flex-wrap items-baseline gap-x-2 text-section font-semibold">
          {title}
          {aside}
        </h2>
        {description ? <p className="text-caption text-muted-foreground">{description}</p> : null}
      </div>
      {onClose ? (
        <Button type="button" variant="ghost" size="icon-sm" aria-label="Close" onClick={onClose}>
          <XIcon aria-hidden="true" />
        </Button>
      ) : null}
    </div>
  );
}

/** What changed in a node or the workflow since the version compared with (5.7). */
function ChangedSince({ changes, compared }: { changes: ValueChange[]; compared: number }) {
  return (
    <section
      aria-label={`Changed since version ${compared}`}
      data-testid="panel-changes"
      className="flex flex-col gap-2 rounded-md border bg-surface-subtle p-3"
    >
      <h3 className="text-caption font-medium text-muted-foreground">
        Changed since version {compared}
      </h3>
      <ValueChanges changes={changes} />
    </section>
  );
}

/** The values that changed since the version compared with, and its number. */
export interface PanelChanges {
  changes: ValueChange[];
  compared: number;
}

/** The selected node's parameters. */
export function NodePanel({
  node,
  manifests,
  pending,
  error,
  retry,
  refusal,
  issues = [],
  changes = null,
  readOnly = false,
  context,
  onEdit,
  onClose,
}: {
  node: SpecNode;
  manifests: NodeManifest[];
  pending: boolean;
  error: string | null;
  retry: () => void;
  /** A refusal (a `422`, an op error) that names this node. */
  refusal: string | null;
  /** What keeps this node from running, as the live check found it (5.6). */
  issues?: string[];
  changes?: PanelChanges | null;
  readOnly?: boolean;
  /** The workspace and the workflow being edited, for a subflow's workflow picker (6.5). */
  context?: BuilderFormContext;
  onEdit: (edit: Edit) => void;
  onClose?: () => void;
}) {
  const manifest = manifests.find((m) => m.kind === node.type);
  const known = isKnownKind(node.type);
  const label = manifest?.label ?? (known ? kindLabel(node.type as NodeKind) : node.type);
  const icon = known ? (
    <KindIcon kind={node.type as NodeKind} className="size-4" />
  ) : (
    <ManifestIcon name={manifest?.icon ?? ""} className="size-4" />
  );
  const values = nodeParams(node, manifest);

  let body: React.ReactNode;
  if (pending) body = <LoadingState label="Loading node types…" />;
  else if (error) body = <ErrorState message={error} onRetry={retry} />;
  else if (!manifest) {
    body = (
      <div className="flex flex-col gap-3">
        <EmptyState icon={SlidersHorizontalIcon} message="No editable parameters for this kind." />
        <JsonView value={node} />
      </div>
    );
  } else {
    const schema = manifest.parameters as Schema;
    body = (
      <ParamForm
        key={node.id}
        idPrefix={`param-${node.id}`}
        schema={schema}
        ui={(manifest.ui ?? {}) as UiSchema}
        values={values}
        readOnly={readOnly}
        context={context}
        onChange={(next) => {
          const edit = paramEdit(node.id, values, next, schema);
          if (edit) onEdit(edit);
        }}
      />
    );
  }

  return (
    <div className="flex min-h-0 flex-col" data-testid="node-panel" data-node={node.id}>
      <PanelHeader
        icon={icon}
        title={label}
        aside={
          <span className="min-w-0 font-mono text-caption font-normal break-all text-foreground-secondary">
            {node.id}
          </span>
        }
        description={manifest?.description}
        onClose={onClose}
      />
      <div className="@container flex flex-col gap-4 overflow-y-auto p-4">
        {refusal ? (
          <p role="alert" className="flex items-start gap-1 text-meta text-status-failed">
            <CircleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            <span>{refusal}</span>
          </p>
        ) : null}
        {issues.length > 0 ? (
          <ul aria-label="Issues" className="flex flex-col gap-1">
            {issues.map((issue) => (
              <li key={issue} className="flex items-start gap-1 text-meta text-status-failed">
                <CircleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                <span>{issue}</span>
              </li>
            ))}
          </ul>
        ) : null}
        {changes && changes.changes.length > 0 ? <ChangedSince {...changes} /> : null}
        {body}
      </div>
    </div>
  );
}

const DOCUMENT_SCHEMA: Schema = {
  type: "object",
  required: ["name"],
  properties: {
    name: { type: "string", minLength: 1, title: "Name" },
    description: { type: "string", title: "Description" },
    budget_usd: {
      type: "number",
      minimum: 0.01,
      maximum: 1_000_000,
      title: "Budget",
      description:
        "What a run of this workflow may spend, a hard stop once reached. A run can set its own. " +
        "Unset: the workspace's default budget, or none.",
    },
  },
};

const DOCUMENT_UI: UiSchema = {
  description: { "ui:widget": "textarea", "ui:options": { rows: 3 } },
  budget_usd: { "ui:widget": "usd", "ui:placeholder": "No budget" },
};

/** The workflow's own fields: name, description and budget. */
export function WorkflowPanel({
  spec,
  changes = null,
  readOnly = false,
  onEdit,
  onClose,
}: {
  spec: WorkflowSpec;
  changes?: PanelChanges | null;
  readOnly?: boolean;
  onEdit: (edit: Edit) => void;
  onClose?: () => void;
}) {
  const values = documentParams(spec);
  return (
    <div className="flex min-h-0 flex-col" data-testid="workflow-panel">
      <PanelHeader
        icon={<SlidersHorizontalIcon aria-hidden="true" className="size-4" />}
        title="Workflow"
        description={
          readOnly
            ? "Select a step to see its parameters."
            : "Select a step to edit its parameters."
        }
        onClose={onClose}
      />
      <div className="@container flex flex-col gap-4 overflow-y-auto p-4">
        {changes && changes.changes.length > 0 ? <ChangedSince {...changes} /> : null}
        <ParamForm
          idPrefix="workflow"
          schema={DOCUMENT_SCHEMA}
          ui={DOCUMENT_UI}
          values={values}
          readOnly={readOnly}
          onChange={(next) => {
            const edit = paramEdit(null, values, next, DOCUMENT_SCHEMA);
            if (edit) onEdit(edit);
          }}
        />
      </div>
    </div>
  );
}
