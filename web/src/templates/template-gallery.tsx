"use client";

import {
  CircleAlertIcon,
  CircleCheckIcon,
  CircleDashedIcon,
  LayoutTemplateIcon,
  PencilRulerIcon,
  PlayIcon,
} from "lucide-react";

import { createElement } from "react";

import { useTemplates, type Template } from "@/api/queries";
import { EmptyState, ErrorState } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { templateIcon } from "@/templates/icons";
import { REQUIREMENT_LABEL, type ConnectionState, type Readiness } from "@/runs/new-run/readiness";

function RequirementChip({ label, state }: { label: string; state: ConnectionState }) {
  const ok = state === "ready";
  const Icon = ok ? CircleCheckIcon : state === "attention" ? CircleAlertIcon : CircleDashedIcon;
  const text = ok ? "connected" : state === "loading" ? "checking" : "not connected";
  return (
    <Badge
      variant="outline"
      data-state={state}
      className={cn(ok ? "text-status-succeeded" : "text-muted-foreground")}
    >
      <Icon aria-hidden="true" data-icon="inline-start" />
      <span className="text-foreground">{label}</span>
      <span className="sr-only">: {text}</span>
    </Badge>
  );
}

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
              <RequirementChip key={r} label={REQUIREMENT_LABEL[r]} state={readiness.state[r]} />
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

/** One card per template from `GET /templates`. Starting one opens the "New run" sheet; editing
 * one opens it as a stored workflow in the builder (5.2). */
export function TemplateGallery({
  readiness,
  onStart,
  onEdit,
  editing = null,
  baseUrl,
}: {
  readiness: Readiness;
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
  if (templates.data.length === 0) {
    return <EmptyState icon={LayoutTemplateIcon} message="No templates are available yet." />;
  }
  return (
    <div className="grid gap-4 md:grid-cols-2">
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
