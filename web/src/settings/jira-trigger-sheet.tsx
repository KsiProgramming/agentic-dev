"use client";

import { LoaderCircleIcon } from "lucide-react";
import Link from "next/link";
import { useId, useMemo, useState, type FormEvent } from "react";
import { toast } from "sonner";

import {
  useCreateJiraTrigger,
  useJiraStatuses,
  useRepos,
  useTemplates,
  type JiraSite,
  type JiraTriggerIn,
} from "@/api/queries";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  NativeSelect,
  NativeSelectOptGroup,
  NativeSelectOption,
} from "@/components/ui/native-select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { FieldMessage } from "@/forms/schema-form/schema-fields";
import { MD_UP, useMediaQuery } from "@/lib/use-media-query";
import { RepoCombobox } from "@/runs/new-run/repo-combobox";
import { useWorkflows } from "@/workflows/api";

interface SheetProps {
  workspaceId: string;
  /** The connection's sites that are on and have projects picked. */
  sites: JiraSite[];
  baseUrl?: string;
  onOpenChange: (open: boolean) => void;
}

/**
 * Adds a Jira trigger: when an issue of a picked project moves to a status or gets a label, a
 * run of a template or stored workflow starts with the issue key as its input. Shaped as the New
 * run sheet: a side sheet from 768 px, a full-height bottom sheet below.
 */
export function JiraTriggerSheet({ open, ...props }: SheetProps & { open: boolean }) {
  const wide = useMediaQuery(MD_UP);
  return (
    <Sheet open={open} onOpenChange={props.onOpenChange}>
      <SheetContent
        side={wide ? "right" : "bottom"}
        className="data-[side=bottom]:h-svh"
        size="sm"
        data-testid="jira-trigger-sheet"
      >
        {open ? <SheetBody {...props} /> : null}
      </SheetContent>
    </Sheet>
  );
}

type Errors = Partial<Record<"value" | "target" | "ref", string>>;

/** Checks the form as the API would, before asking it. */
export function checkTrigger(form: {
  on: "status" | "label";
  value: string;
  target: string;
  ref: string;
}): Errors {
  const errors: Errors = {};
  const value = form.value.trim();
  if (!value) errors.value = form.on === "status" ? "Pick a status." : "Write a label.";
  else if (form.on === "label" && /\s/.test(value)) errors.value = "A Jira label has no spaces.";
  if (!form.target) errors.target = "Pick what runs.";
  if (form.ref.includes("..")) errors.ref = "A branch name cannot hold “..”.";
  return errors;
}

function SheetBody({ workspaceId, sites, baseUrl, onOpenChange }: SheetProps) {
  const formId = useId();
  const ids = {
    site: useId(),
    project: useId(),
    on: useId(),
    value: useId(),
    target: useId(),
    repo: useId(),
    ref: useId(),
  };
  const [cloudId, setCloudId] = useState(sites[0]?.cloud_id ?? "");
  const site = sites.find((s) => s.cloud_id === cloudId) ?? sites[0];
  const [projectKey, setProjectKey] = useState(site?.projects[0]?.key ?? "");
  const [on, setOn] = useState<"status" | "label">("status");
  const [value, setValue] = useState("");
  const [target, setTarget] = useState("");
  const [repo, setRepo] = useState("");
  const [ref, setRef] = useState("");
  const [errors, setErrors] = useState<Errors>({});

  const statuses = useJiraStatuses({ workspaceId, cloudId, projectKey, baseUrl });
  const templates = useTemplates({ baseUrl });
  const workflows = useWorkflows(workspaceId, true, baseUrl);
  const repos = useRepos({ workspaceId, baseUrl });
  const create = useCreateJiraTrigger({ workspaceId, baseUrl });

  // Only a workflow that takes a text input can receive the issue key: not a spec file (7.7).
  const runnable = useMemo(
    () => (templates.data ?? []).filter((t) => t.input?.required && t.input.kind !== "spec_file"),
    [templates.data],
  );

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const found = checkTrigger({ on, value, target, ref });
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    const [kind, id] = [
      target.slice(0, target.indexOf(":")),
      target.slice(target.indexOf(":") + 1),
    ];
    const rule: JiraTriggerIn = {
      cloud_id: cloudId,
      project_key: projectKey,
      on,
      value: value.trim(),
      template_id: kind === "template" ? id : null,
      workflow: kind === "workflow" ? { id } : null,
      repo: repo ? { url: repo, ref: ref.trim() || null } : null,
      enabled: true,
    };
    create.mutate(rule, {
      onSuccess: () => {
        toast.success("Trigger added.");
        onOpenChange(false);
      },
    });
  }

  const pending = create.isPending;
  const statusControl = (() => {
    if (on === "label") {
      return (
        <Input
          id={ids.value}
          value={value}
          autoComplete="off"
          spellCheck={false}
          placeholder="agent"
          aria-invalid={errors.value ? true : undefined}
          aria-describedby={errors.value ? `${ids.value}-error` : `${ids.value}-help`}
          disabled={pending}
          onChange={(e) => setValue(e.target.value)}
        />
      );
    }
    if (statuses.isError) {
      // Jira could not list them: the status is typed instead.
      return (
        <Input
          id={ids.value}
          value={value}
          autoComplete="off"
          placeholder="In Progress"
          aria-invalid={errors.value ? true : undefined}
          aria-describedby={errors.value ? `${ids.value}-error` : `${ids.value}-help`}
          disabled={pending}
          onChange={(e) => setValue(e.target.value)}
        />
      );
    }
    return (
      <NativeSelect
        id={ids.value}
        value={value}
        aria-invalid={errors.value ? true : undefined}
        aria-describedby={errors.value ? `${ids.value}-error` : `${ids.value}-help`}
        disabled={pending || statuses.isPending}
        onChange={(e) => setValue(e.target.value)}
      >
        <NativeSelectOption value="">
          {statuses.isPending ? "Loading statuses…" : "Pick a status"}
        </NativeSelectOption>
        {(statuses.data ?? []).map((name) => (
          <NativeSelectOption key={name} value={name}>
            {name}
          </NativeSelectOption>
        ))}
      </NativeSelect>
    );
  })();

  return (
    <>
      <SheetHeader>
        <SheetTitle>New trigger</SheetTitle>
        <SheetDescription>
          A run starts on an issue when it moves to a status or gets a label. The run is given the
          issue key; it reads the issue itself.
        </SheetDescription>
      </SheetHeader>
      <form
        id={formId}
        onSubmit={onSubmit}
        noValidate
        className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-4"
      >
        {sites.length > 1 ? (
          <Field>
            <FieldLabel htmlFor={ids.site}>Jira site</FieldLabel>
            <NativeSelect
              id={ids.site}
              value={cloudId}
              disabled={pending}
              onChange={(e) => {
                const next = sites.find((s) => s.cloud_id === e.target.value);
                setCloudId(e.target.value);
                setProjectKey(next?.projects[0]?.key ?? "");
                setValue("");
              }}
            >
              {sites.map((s) => (
                <NativeSelectOption key={s.cloud_id} value={s.cloud_id}>
                  {s.name}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </Field>
        ) : null}
        <Field>
          <FieldLabel htmlFor={ids.project}>Project</FieldLabel>
          <NativeSelect
            id={ids.project}
            value={projectKey}
            disabled={pending}
            onChange={(e) => {
              setProjectKey(e.target.value);
              if (on === "status") setValue("");
            }}
          >
            {(site?.projects ?? []).map((p) => (
              <NativeSelectOption key={p.id} value={p.key}>
                {p.key} · {p.name}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </Field>
        <Field>
          <FieldLabel htmlFor={ids.on}>When an issue</FieldLabel>
          <NativeSelect
            id={ids.on}
            value={on}
            disabled={pending}
            onChange={(e) => {
              setOn(e.target.value === "label" ? "label" : "status");
              setValue("");
            }}
          >
            <NativeSelectOption value="status">moves to a status</NativeSelectOption>
            <NativeSelectOption value="label">gets a label</NativeSelectOption>
          </NativeSelect>
        </Field>
        <Field data-invalid={errors.value ? true : undefined}>
          <FieldLabel htmlFor={ids.value}>{on === "status" ? "Status" : "Label"}</FieldLabel>
          {statusControl}
          {errors.value ? (
            <FieldMessage id={`${ids.value}-error`}>{errors.value}</FieldMessage>
          ) : (
            <FieldDescription id={`${ids.value}-help`}>
              {on === "status"
                ? "A move into this status starts a run, whichever status it came from."
                : "Adding this label, or creating an issue with it, starts a run."}
            </FieldDescription>
          )}
        </Field>
        <Field data-invalid={errors.target ? true : undefined}>
          <FieldLabel htmlFor={ids.target}>Run</FieldLabel>
          <NativeSelect
            id={ids.target}
            value={target}
            aria-invalid={errors.target ? true : undefined}
            aria-describedby={errors.target ? `${ids.target}-error` : `${ids.target}-help`}
            disabled={pending}
            onChange={(e) => setTarget(e.target.value)}
          >
            <NativeSelectOption value="">Pick a template or workflow</NativeSelectOption>
            {runnable.length > 0 ? (
              <NativeSelectOptGroup label="Templates">
                {runnable.map((t) => (
                  <NativeSelectOption key={t.id} value={`template:${t.id}`}>
                    {t.name}
                  </NativeSelectOption>
                ))}
              </NativeSelectOptGroup>
            ) : null}
            {(workflows.data ?? []).length > 0 ? (
              <NativeSelectOptGroup label="Workflows">
                {(workflows.data ?? []).map((w) => (
                  <NativeSelectOption key={w.workflow_id} value={`workflow:${w.workflow_id}`}>
                    {w.name}
                  </NativeSelectOption>
                ))}
              </NativeSelectOptGroup>
            ) : null}
          </NativeSelect>
          {errors.target ? (
            <FieldMessage id={`${ids.target}-error`}>{errors.target}</FieldMessage>
          ) : (
            <FieldDescription id={`${ids.target}-help`}>
              Its input is the issue key. A workflow runs its latest version.
            </FieldDescription>
          )}
        </Field>
        <Field>
          <FieldLabel htmlFor={ids.repo}>Repository</FieldLabel>
          {repos.data?.state === "connected" ? (
            <RepoCombobox
              id={ids.repo}
              repos={repos.data.repos}
              value={repo}
              onChange={setRepo}
              describedBy={`${ids.repo}-help`}
              disabled={pending}
            />
          ) : (
            <p className="text-meta text-foreground-secondary">
              <Link href="/settings/integrations" className="text-foreground underline">
                Connect GitHub
              </Link>{" "}
              to pick a repository.
            </p>
          )}
          <FieldDescription id={`${ids.repo}-help`}>
            For a workflow that works on code. Leave it empty for one that only reads Jira.
          </FieldDescription>
        </Field>
        {repo ? (
          <Field data-invalid={errors.ref ? true : undefined}>
            <FieldLabel htmlFor={ids.ref}>Branch (optional)</FieldLabel>
            <Input
              id={ids.ref}
              value={ref}
              autoComplete="off"
              spellCheck={false}
              className="font-mono"
              placeholder="The default branch"
              aria-invalid={errors.ref ? true : undefined}
              aria-describedby={errors.ref ? `${ids.ref}-error` : undefined}
              disabled={pending}
              onChange={(e) => setRef(e.target.value)}
            />
            {errors.ref ? <FieldMessage id={`${ids.ref}-error`}>{errors.ref}</FieldMessage> : null}
          </Field>
        ) : null}
        {create.error ? (
          <Alert variant="destructive">
            <AlertDescription>{create.error.message}</AlertDescription>
          </Alert>
        ) : null}
      </form>
      <SheetFooter className="flex-row justify-end gap-2">
        <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
          Cancel
        </Button>
        <Button type="submit" form={formId} disabled={pending}>
          {pending ? (
            <LoaderCircleIcon
              aria-hidden="true"
              data-icon="inline-start"
              className="motion-safe:animate-spin"
            />
          ) : null}
          {pending ? "Saving…" : "Add trigger"}
        </Button>
      </SheetFooter>
    </>
  );
}
