"use client";

import {
  LayoutTemplateIcon,
  PencilRulerIcon,
  PlayIcon,
  PlusIcon,
  SquareDashedIcon,
} from "lucide-react";

import { createElement } from "react";

import { useTemplates, type Template } from "@/api/queries";
import { EmptyState, ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { templateIcon } from "@/templates/icons";
import { ConnectionChip } from "@/runs/new-run/connection-chip";
import { REQUIREMENT_LABEL, type Readiness } from "@/runs/new-run/readiness";

function TemplateCard({
  template,
  readiness,
  onStart,
  onEdit,
  editing,
}: {
  template: Template;
  readiness: Readiness;
  onStart: (id: string) => void;
  onEdit?: (id: string) => void;
  editing: boolean;
}) {
  const headingId = `template-${template.id}`;
  return (
    <Card
      role="article"
      aria-labelledby={headingId}
      data-testid="template-card"
      className="flex flex-col"
    >
      <CardHeader className="flex flex-1 flex-col gap-3">
        <span className="flex size-9 items-center justify-center rounded-md border bg-surface-subtle">
          {createElement(templateIcon(template.id), { "aria-hidden": true, className: "size-4" })}
        </span>
        <CardTitle>
          <h2 id={headingId}>{template.name}</h2>
        </CardTitle>
        <CardDescription>{template.description}</CardDescription>
      </CardHeader>
      <CardFooter className="flex flex-wrap items-center justify-between gap-3">
        {template.requires.length > 0 ? (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-caption font-medium text-muted-foreground">Requires</span>
            {template.requires.map((r) => (
              <ConnectionChip key={r} label={REQUIREMENT_LABEL[r]} state={readiness.state[r]} />
            ))}
          </div>
        ) : (
          <span />
        )}
        <div className="flex flex-wrap items-center gap-2">
          {onEdit ? (
            <Button
              type="button"
              variant="outline"
              disabled={editing}
              onClick={() => onEdit(template.id)}
            >
              <PencilRulerIcon aria-hidden="true" data-icon="inline-start" />
              {editing ? "Opening…" : "Edit in builder"}
              <span className="sr-only"> {template.name}</span>
            </Button>
          ) : null}
          <Button type="button" onClick={() => onStart(template.id)}>
            <PlayIcon aria-hidden="true" data-icon="inline-start" />
            Start
            <span className="sr-only"> {template.name}</span>
          </Button>
        </div>
      </CardFooter>
    </Card>
  );
}

/** Starts a workflow from nothing (5.8): opens the new workflow sheet. */
function BlankCanvasCard({ onCreate }: { onCreate: () => void }) {
  return (
    <Card
      role="article"
      aria-labelledby="template-blank-canvas"
      data-testid="blank-canvas-card"
      className="flex flex-col"
    >
      <CardHeader className="flex flex-1 flex-col gap-3">
        <span className="flex size-9 items-center justify-center rounded-md border border-dashed border-border-strong bg-surface-subtle">
          <SquareDashedIcon aria-hidden="true" className="size-4" />
        </span>
        <CardTitle>
          <h2 id="template-blank-canvas">Blank canvas</h2>
        </CardTitle>
        <CardDescription>Draw your own workflow, one step at a time.</CardDescription>
      </CardHeader>
      <CardFooter className="flex justify-end">
        <Button type="button" variant="outline" onClick={onCreate}>
          <PlusIcon aria-hidden="true" data-icon="inline-start" />
          Create
          <span className="sr-only"> a blank workflow</span>
        </Button>
      </CardFooter>
    </Card>
  );
}

/** The blank canvas card (5.8), then one card per template from `GET /templates`. Starting one opens the "New run" sheet; editing
 * one opens it as a stored workflow in the builder (5.2). */
export function TemplateGallery({
  readiness,
  onStart,
  onEdit,
  onBlank,
  editing = null,
  baseUrl,
}: {
  readiness: Readiness;
  /** Shows the blank canvas card first, which calls this. */
  onBlank?: () => void;
  onStart: (id: string) => void;
  onEdit?: (id: string) => void;
  /** The template being opened in the builder. */
  editing?: string | null;
  baseUrl?: string;
}) {
  const templates = useTemplates({ baseUrl });

  if (templates.isPending) {
    return (
      <div role="status" className="grid gap-4 md:grid-cols-2">
        <span className="sr-only">Loading templates…</span>
        {[0, 1].map((i) => (
          <Skeleton key={i} aria-hidden="true" className="h-48 rounded-xl" />
        ))}
      </div>
    );
  }
  if (templates.isError) {
    return (
      <ErrorState message={templates.error.message} onRetry={() => void templates.refetch()} />
    );
  }
  if (templates.data.length === 0 && !onBlank) {
    return <EmptyState icon={LayoutTemplateIcon} message="No templates are available yet." />;
  }
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {onBlank ? <BlankCanvasCard onCreate={onBlank} /> : null}
      {templates.data.map((template) => (
        <TemplateCard
          key={template.id}
          template={template}
          readiness={readiness}
          onStart={onStart}
          onEdit={onEdit}
          editing={editing === template.id}
        />
      ))}
    </div>
  );
}
