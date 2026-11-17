"use client";

import { LoaderCircleIcon } from "lucide-react";
import { useId, useState } from "react";
import { toast } from "sonner";

import {
  useJiraFields,
  usePutJiraProjectFields,
  type JiraFieldRole,
  type JiraProject,
  type JiraProjectFields,
  type JiraSite,
} from "@/api/queries";
import { ErrorState, LoadingState } from "@/components/states";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { MD_UP, useMediaQuery } from "@/lib/use-media-query";

/** The fixed roles a project maps (7.4), in the order the sheet asks for them. */
export const ROLES: readonly { role: JiraFieldRole; label: string; help: string; none: string }[] =
  [
    {
      role: "acceptance_criteria",
      label: "Acceptance criteria",
      help: "A paragraph or short-text field. Agents read it as what done means.",
      none: "This site has no paragraph or short-text field. Add one in Jira, then come back.",
    },
    {
      role: "story_points",
      label: "Story points",
      help: "A number field, such as Story point estimate.",
      none: "This site has no number field. Turn on estimation in Jira, then come back.",
    },
  ];

/** Whether a project maps any field; the Jira card says so on each project. */
export function hasMappedFields(project: JiraProject): boolean {
  const fields = project.fields;
  return Boolean(fields?.acceptance_criteria || fields?.story_points);
}

interface SheetProps {
  site: JiraSite;
  workspaceId: string;
  baseUrl?: string;
  onOpenChange: (open: boolean) => void;
}

/**
 * Says which of a picked project's Jira fields hold its acceptance criteria and its story
 * points, so the agents of a run started from one of its issues are told them. A side sheet
 * from 768 px, a full-height bottom sheet below.
 */
export function JiraFieldsSheet({ open, ...props }: SheetProps & { open: boolean }) {
  const wide = useMediaQuery(MD_UP);
  return (
    <Sheet open={open} onOpenChange={props.onOpenChange}>
      <SheetContent
        side={wide ? "right" : "bottom"}
        className="data-[side=bottom]:h-svh"
        size="sm"
        data-testid="jira-fields-sheet"
      >
        {/* Mounted only while open, so a closed sheet asks Jira for nothing. */}
        <SheetBody {...props} />
      </SheetContent>
    </Sheet>
  );
}

function SheetBody({ site, workspaceId, baseUrl, onOpenChange }: SheetProps) {
  const projectId = useId();
  const [projectKey, setProjectKey] = useState(site.projects[0]?.key ?? "");
  const project = site.projects.find((p) => p.key === projectKey);
  return (
    <>
      <SheetHeader>
        <SheetTitle>Fields of {site.name}</SheetTitle>
        <SheetDescription>
          Runs started from an issue tell every agent these fields, with the issue&apos;s components
          and description.
        </SheetDescription>
      </SheetHeader>
      <div className="px-4">
        <Field>
          <FieldLabel htmlFor={projectId}>Project</FieldLabel>
          <NativeSelect
            id={projectId}
            value={projectKey}
            onChange={(e) => setProjectKey(e.target.value)}
          >
            {site.projects.map((p) => (
              <NativeSelectOption key={p.id} value={p.key}>
                {p.key} · {p.name}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </Field>
      </div>
      {project ? (
        // A new form per project, starting from its own mapping.
        <MappingForm
          key={project.key}
          site={site}
          project={project}
          workspaceId={workspaceId}
          baseUrl={baseUrl}
          onOpenChange={onOpenChange}
        />
      ) : null}
    </>
  );
}

function MappingForm({
  site,
  project,
  workspaceId,
  baseUrl,
  onOpenChange,
}: SheetProps & { project: JiraProject }) {
  const [chosen, setChosen] = useState<Record<JiraFieldRole, string>>(() => ({
    acceptance_criteria: project.fields?.acceptance_criteria?.id ?? "",
    story_points: project.fields?.story_points?.id ?? "",
  }));
  const save = usePutJiraProjectFields({ workspaceId, baseUrl });
  return (
    <>
      <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-4">
        {ROLES.map((r) => (
          <RoleField
            key={r.role}
            {...r}
            site={site}
            project={project}
            workspaceId={workspaceId}
            baseUrl={baseUrl}
            mapped={project.fields?.[r.role] ?? null}
            value={chosen[r.role]}
            disabled={save.isPending}
            onChange={(id) => setChosen((current) => ({ ...current, [r.role]: id }))}
          />
        ))}
      </div>
      {save.error ? (
        <Alert variant="destructive" className="mx-4 w-auto">
          <AlertDescription>{save.error.message}</AlertDescription>
        </Alert>
      ) : null}
      <SheetFooter className="flex-row items-center justify-end gap-2">
        <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
          Cancel
        </Button>
        <Button
          type="button"
          disabled={save.isPending}
          onClick={() =>
            save.mutate(
              {
                cloudId: site.cloud_id,
                projectKey: project.key,
                fields: {
                  acceptance_criteria: chosen.acceptance_criteria || null,
                  story_points: chosen.story_points || null,
                },
              },
              {
                onSuccess: () => {
                  toast.success(`Fields of ${project.key} saved.`);
                  onOpenChange(false);
                },
              },
            )
          }
        >
          {save.isPending ? (
            <LoaderCircleIcon
              aria-hidden="true"
              data-icon="inline-start"
              className="motion-safe:animate-spin"
            />
          ) : null}
          {save.isPending ? "Saving…" : "Save fields"}
        </Button>
      </SheetFooter>
    </>
  );
}

function RoleField({
  role,
  label,
  help,
  none,
  site,
  project,
  workspaceId,
  baseUrl,
  mapped,
  value,
  disabled,
  onChange,
}: {
  role: JiraFieldRole;
  label: string;
  help: string;
  none: string;
  site: JiraSite;
  project: JiraProject;
  workspaceId: string;
  baseUrl?: string;
  mapped: JiraProjectFields[JiraFieldRole];
  value: string;
  disabled: boolean;
  onChange: (fieldId: string) => void;
}) {
  const id = useId();
  const fields = useJiraFields({
    workspaceId,
    cloudId: site.cloud_id,
    role,
    projectKey: project.key,
    baseUrl,
  });
  if (fields.isPending) {
    return (
      <Field>
        <FieldLabel>{label}</FieldLabel>
        <LoadingState rows={1} label={`Loading the fields for ${label.toLowerCase()}…`} />
      </Field>
    );
  }
  if (fields.isError) {
    return (
      <Field>
        <FieldLabel>{label}</FieldLabel>
        <ErrorState message={fields.error.message} onRetry={() => void fields.refetch()} />
      </Field>
    );
  }
  const listed = fields.data;
  // A mapped field Jira no longer lists stays visible, so saving does not drop it unseen.
  const gone = mapped && !listed.some((f) => f.id === mapped.id) ? mapped : null;
  const empty = listed.length === 0 && !gone;
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <NativeSelect
        id={id}
        value={value}
        disabled={disabled || empty}
        aria-describedby={`${id}-help`}
        onChange={(e) => onChange(e.target.value)}
      >
        <NativeSelectOption value="">Not mapped</NativeSelectOption>
        {listed.map((f) => (
          // Field names come from Jira: shown as text.
          <NativeSelectOption key={f.id} value={f.id}>
            {f.name} · {f.type}
            {f.suggested ? " · suggested" : ""}
          </NativeSelectOption>
        ))}
        {gone ? (
          <NativeSelectOption value={gone.id}>{gone.name} · no longer in Jira</NativeSelectOption>
        ) : null}
      </NativeSelect>
      <FieldDescription id={`${id}-help`}>{empty ? none : help}</FieldDescription>
    </Field>
  );
}
