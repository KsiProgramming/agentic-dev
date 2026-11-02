"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { LoaderCircleIcon, PlayIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useId, useMemo, useState } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { createApiClient } from "@/api/client";
import { ApiError, codeOf, detailOf, failure, messageOf, validationIssues } from "@/api/errors";
import {
  useNewRepoOptions,
  usePolicy,
  useTemplates,
  type Requirement,
  type Template,
} from "@/api/queries";
import { ErrorState, LoadingState } from "@/components/states";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { MD_UP, useMediaQuery } from "@/lib/use-media-query";
import {
  defaultValues,
  parameterErrors,
  parseSchema,
  toParameters,
  toZod,
  type FieldSpec,
  type FormValues,
} from "@/forms/schema-form/schema";
import { FieldMessage, SchemaFields } from "@/forms/schema-form/schema-fields";
import { budgetSchema, isBudgetError, parseBudget } from "@/runs/budget";
import { formatUsd } from "@/runs/cost";
import { runsKey } from "@/runs/use-run-summaries";

import { ConnectionChecklist } from "./connection-checklist";
import { loadLastRepo, saveLastRepo } from "./last-repo";
import {
  EMPTY_NEW_REPO,
  NewRepoFields,
  newRepoNameError,
  toNewRepo,
  type NewRepoValues,
} from "./new-repo-fields";
import { isReady, useReadiness, type Readiness } from "./readiness";
import { RepoCombobox } from "./repo-combobox";

/** Whether the run works on a repo the GitHub App can reach, or on one it creates. */
type RepoMode = "existing" | "new";

interface Values {
  repoMode: RepoMode;
  repo: string;
  newRepo: NewRepoValues;
  params: FormValues;
  /** What the first step of a stored workflow is given; templates take their options instead. */
  input: string;
  /** "" runs with the workspace's default budget. */
  budget: string;
}

/** A version of a stored workflow to run (5.7), and the connections it needs. */
export interface StoredWorkflowSource {
  id: string;
  version: number;
  name: string;
  requires: Requirement[];
}

/** What a run is started from: a template with its options, or a stored workflow's version. */
type RunSource = { template: Template } | { workflow: StoredWorkflowSource };

const requiresOf = (source: RunSource) =>
  "template" in source ? source.template.requires : source.workflow.requires;

/** The problems of a `policy_limits` refusal, or null for any other body. */
function policyErrors(error: unknown): string[] | null {
  const detail = detailOf(error);
  if (codeOf(error) !== "policy_limits" || !detail || typeof detail !== "object") return null;
  const errors = "errors" in detail ? detail.errors : null;
  return Array.isArray(errors) ? errors.filter((e): e is string => typeof e === "string") : null;
}

/** Where GitHub's install sends the browser back to: this template's sheet. */
export function sheetPath(templateId: string) {
  return `/templates?template=${encodeURIComponent(templateId)}`;
}

function NewRunForm({
  source,
  fields,
  readiness,
  workspaceId,
  baseUrl,
  formId,
  onPendingChange,
  onBlockedChange,
  navigate,
}: {
  source: RunSource;
  /** The template's options; none for a stored workflow. */
  fields: FieldSpec[];
  readiness: Readiness;
  workspaceId: string;
  baseUrl?: string;
  formId: string;
  onPendingChange: (pending: boolean) => void;
  /** Whether the form can be sent as it is: not while a new repo cannot be created. */
  onBlockedChange: (blocked: boolean) => void;
  navigate?: (url: string) => void;
}) {
  const router = useRouter();
  const queries = useQueryClient();
  const repoId = useId();
  const inputId = useId();
  const budgetId = useId();
  const policy = usePolicy({ workspaceId, baseUrl });
  const defaultBudget = policy.data?.effective.budget_usd ?? null;
  const needsRepo = requiresOf(source).includes("github");
  const schema = useMemo(
    () =>
      z
        .object({
          repoMode: z.enum(["existing", "new"]),
          repo: z.string(),
          newRepo: z.object({
            name: z.string(),
            private: z.boolean(),
            description: z.string().max(350, "Keep it under 350 characters."),
            gitignore: z.string(),
            license: z.string(),
          }),
          params: toZod(fields),
          input: z.string().max(20_000, "Keep it under 20,000 characters."),
          budget: budgetSchema(),
        })
        .superRefine((values, ctx) => {
          if (!needsRepo) return;
          if (values.repoMode === "existing" && values.repo === "") {
            ctx.addIssue({ code: "custom", path: ["repo"], message: "Pick a repository." });
          }
          const nameError = newRepoNameError(values.newRepo.name);
          if (values.repoMode === "new" && nameError) {
            ctx.addIssue({ code: "custom", path: ["newRepo", "name"], message: nameError });
          }
        }),
    [fields, needsRepo],
  );
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      repoMode: "existing",
      repo: "",
      newRepo: EMPTY_NEW_REPO,
      params: defaultValues(fields),
      input: "",
      budget: "",
    },
  });
  const { isSubmitting } = form.formState;
  const rootError = form.formState.errors.root?.message;
  const repoMode = useWatch({ control: form.control, name: "repoMode" });
  const creating = needsRepo && repoMode === "new";
  const newRepoOptions = useNewRepoOptions({ workspaceId, baseUrl, enabled: creating });
  const blocked = creating && newRepoOptions.data?.can_create !== true;

  useEffect(() => onPendingChange(isSubmitting), [isSubmitting, onPendingChange]);
  useEffect(() => onBlockedChange(blocked), [blocked, onBlockedChange]);

  // Preselect the last used repo once the list is in, if it is still there.
  const repos = readiness.repos;
  useEffect(() => {
    if (!needsRepo || form.getValues("repo") !== "") return;
    const last = loadLastRepo(workspaceId);
    if (last && repos.some((r) => r.html_url === last)) form.setValue("repo", last);
  }, [needsRepo, repos, workspaceId, form]);

  async function onSubmit(values: Values) {
    let result;
    try {
      result = await createApiClient(baseUrl).POST("/runs", {
        body: {
          ...("template" in source
            ? {
                template: {
                  id: source.template.id,
                  parameters: toParameters(fields, values.params),
                },
              }
            : {
                stored_workflow: { id: source.workflow.id, version: source.workflow.version },
              }),
          input: values.input,
          repo: needsRepo && !creating ? { url: values.repo } : null,
          ...(creating ? { new_repo: toNewRepo(values.newRepo) } : {}),
          workspace_id: workspaceId,
          trigger: "manual",
          budget_usd: parseBudget(values.budget),
        },
      });
    } catch (err) {
      form.setError("root", { message: failure(err) });
      return;
    }
    const { data, error, response } = result;
    if (!data) {
      const message = messageOf(error);
      const budgetIssue = validationIssues(error).find((i) => i.loc.at(-1) === "budget_usd");
      const budgetProblems = policyErrors(error)?.filter(isBudgetError) ?? [];
      if (response.status === 422 && (budgetIssue || budgetProblems.length > 0)) {
        form.setError("budget", { message: budgetIssue?.msg ?? budgetProblems.join(" ") });
        return;
      }
      if (response.status === 422 && message) {
        const { byField, rest } = parameterErrors(message);
        for (const [name, why] of Object.entries(byField)) {
          form.setError(`params.${name}`, { message: why });
        }
        if (rest || Object.keys(byField).length === 0) {
          form.setError("root", { message: rest ?? message });
        }
        return;
      }
      if (response.status === 409 && codeOf(error) === "repo_exists") {
        form.setError("newRepo.name", { message: message ?? "This repository already exists." });
        return;
      }
      form.setError("root", {
        message: new ApiError(response.status, error, "Could not start the run").message,
      });
      return;
    }
    if (needsRepo && !creating) saveLastRepo(workspaceId, values.repo);
    void queries.invalidateQueries({ queryKey: runsKey(workspaceId) });
    if (navigate) navigate(`/runs/${data.run_id}`);
    else router.push(`/runs/${data.run_id}`);
  }

  return (
    <form
      id={formId}
      onSubmit={(e) => void form.handleSubmit(onSubmit)(e)}
      noValidate
      className="flex flex-col gap-5"
    >
      {needsRepo && readiness.state.github === "ready" ? (
        <Tabs
          value={repoMode}
          onValueChange={(mode) => form.setValue("repoMode", mode as RepoMode)}
          className="gap-4"
        >
          <TabsList variant="segmented" aria-label="Where the run works" className="w-full">
            <TabsTrigger value="existing" disabled={isSubmitting}>
              Existing repo
            </TabsTrigger>
            <TabsTrigger value="new" disabled={isSubmitting}>
              New repo
            </TabsTrigger>
          </TabsList>
          <TabsContent value="existing">
            <Controller
              name="repo"
              control={form.control}
              render={({ field, fieldState }) => (
                <Field data-invalid={fieldState.error ? true : undefined}>
                  <FieldLabel htmlFor={repoId}>Repository</FieldLabel>
                  <RepoCombobox
                    id={repoId}
                    repos={repos}
                    value={field.value}
                    onChange={field.onChange}
                    manageUrl={readiness.manageUrl}
                    invalid={fieldState.error !== undefined}
                    describedBy={fieldState.error ? `${repoId}-error` : `${repoId}-help`}
                    disabled={isSubmitting}
                  />
                  {fieldState.error?.message ? (
                    <FieldMessage id={`${repoId}-error`}>{fieldState.error.message}</FieldMessage>
                  ) : (
                    <FieldDescription id={`${repoId}-help`}>
                      The run works on a copy and opens a pull request after you approve.
                    </FieldDescription>
                  )}
                </Field>
              )}
            />
          </TabsContent>
          <TabsContent value="new">
            {newRepoOptions.isPending ? (
              <LoadingState rows={3} label="Checking where a repository can be created…" />
            ) : newRepoOptions.isError ? (
              <ErrorState
                message={newRepoOptions.error.message}
                onRetry={() => void newRepoOptions.refetch()}
              />
            ) : newRepoOptions.data.can_create ? (
              <NewRepoFields
                control={form.control}
                options={newRepoOptions.data}
                disabled={isSubmitting}
              />
            ) : (
              <Alert data-testid="new-repo-refused">
                <AlertDescription>
                  {newRepoOptions.data.message ?? "A new repository cannot be created here."}
                </AlertDescription>
              </Alert>
            )}
          </TabsContent>
        </Tabs>
      ) : null}
      <SchemaFields
        fields={fields}
        control={form.control}
        prefix="params"
        disabled={isSubmitting}
      />
      {"workflow" in source ? (
        <Controller
          name="input"
          control={form.control}
          render={({ field, fieldState }) => (
            <Field data-invalid={fieldState.error ? true : undefined}>
              <FieldLabel htmlFor={inputId}>Input</FieldLabel>
              <Textarea
                id={inputId}
                rows={4}
                aria-invalid={fieldState.error ? true : undefined}
                aria-describedby={fieldState.error ? `${inputId}-error` : `${inputId}-help`}
                disabled={isSubmitting}
                {...field}
              />
              {fieldState.error?.message ? (
                <FieldMessage id={`${inputId}-error`}>{fieldState.error.message}</FieldMessage>
              ) : (
                <FieldDescription id={`${inputId}-help`}>
                  Optional. What the first step is given to work on.
                </FieldDescription>
              )}
            </Field>
          )}
        />
      ) : null}
      <Controller
        name="budget"
        control={form.control}
        render={({ field, fieldState }) => (
          <Field data-invalid={fieldState.error ? true : undefined}>
            <FieldLabel htmlFor={budgetId}>Budget (USD)</FieldLabel>
            <Input
              id={budgetId}
              inputMode="decimal"
              autoComplete="off"
              placeholder={defaultBudget === null ? "No budget" : formatUsd(defaultBudget)}
              className="tabular-nums"
              aria-invalid={fieldState.error ? true : undefined}
              aria-describedby={fieldState.error ? `${budgetId}-error` : `${budgetId}-help`}
              disabled={isSubmitting}
              {...field}
            />
            {fieldState.error?.message ? (
              <FieldMessage id={`${budgetId}-error`}>{fieldState.error.message}</FieldMessage>
            ) : (
              <FieldDescription id={`${budgetId}-help`}>
                {defaultBudget === null
                  ? "Optional. The run stops once its cost reaches this; empty runs without a cap."
                  : `Optional. The run stops once its cost reaches this; empty uses the workspace's ${formatUsd(defaultBudget)}.`}
              </FieldDescription>
            )}
          </Field>
        )}
      />
      {rootError ? (
        <Alert variant="destructive">
          <AlertDescription>{rootError}</AlertDescription>
        </Alert>
      ) : null}
    </form>
  );
}

/**
 * Starts a run of a template: its required connections ("Before you start"), the repository and
 * the template's options, generated from its JSON Schema. A side sheet from 768 px, a full-height
 * bottom sheet below. Without `templateId`, a template is picked first.
 */
export function NewRunSheet({ open, onOpenChange, ...props }: SheetProps & { open: boolean }) {
  const wide = useMediaQuery(MD_UP);
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side={wide ? "right" : "bottom"}
        className="data-[side=bottom]:h-svh"
        size="sm"
        data-testid="new-run-sheet"
      >
        {/* Mounted only while open, so a closed sheet asks the API for nothing. */}
        <SheetBody onOpenChange={onOpenChange} {...props} />
      </SheetContent>
    </Sheet>
  );
}

interface SheetProps {
  onOpenChange: (open: boolean) => void;
  templateId: string | null;
  /** Set when the sheet may pick its template (opened from the Runs page). */
  onTemplateChange?: (id: string) => void;
  workspaceId: string;
  baseUrl?: string;
  navigate?: (url: string) => void;
}

function SheetBody({
  onOpenChange,
  templateId,
  onTemplateChange,
  workspaceId,
  baseUrl,
  navigate,
}: SheetProps) {
  const templates = useTemplates({ baseUrl });
  const readiness = useReadiness({ workspaceId, baseUrl });
  const formId = useId();
  const pickerId = useId();
  const [pending, setPending] = useState(false);
  const [blocked, setBlocked] = useState(false);

  const list = templates.data ?? [];
  // A single template needs no picking.
  const chosenId = templateId ?? (list.length === 1 ? (list[0]?.id ?? null) : null);
  const template = list.find((t) => t.id === chosenId) ?? null;
  const parsed = useMemo(() => (template ? parseSchema(template.parameters) : null), [template]);
  const ready = template ? isReady(readiness, template.requires) : false;

  let body;
  if (templates.isPending) body = <LoadingState rows={4} label="Loading templates…" />;
  else if (templates.isError) {
    body = (
      <ErrorState message={templates.error.message} onRetry={() => void templates.refetch()} />
    );
  } else if (templateId !== null && template === null) {
    body = <ErrorState message={`There is no template "${templateId}".`} />;
  } else {
    body = (
      <>
        {onTemplateChange && list.length > 1 ? (
          <Field>
            <FieldLabel htmlFor={pickerId}>Template</FieldLabel>
            <NativeSelect
              id={pickerId}
              value={chosenId ?? ""}
              onChange={(e) => onTemplateChange(e.target.value)}
            >
              <NativeSelectOption value="" disabled>
                Pick a template
              </NativeSelectOption>
              {list.map((t) => (
                <NativeSelectOption key={t.id} value={t.id}>
                  {t.name}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </Field>
        ) : null}
        {template && parsed ? (
          <>
            {template.requires.length > 0 ? (
              <ConnectionChecklist
                requires={template.requires}
                readiness={readiness}
                workspaceId={workspaceId}
                baseUrl={baseUrl}
                returnTo={sheetPath(template.id)}
                navigate={navigate}
              />
            ) : null}
            {"error" in parsed ? (
              <ErrorState
                message={`This template's options cannot be shown here (${parsed.error}).`}
              />
            ) : (
              <NewRunForm
                key={template.id}
                source={{ template }}
                fields={parsed.fields}
                readiness={readiness}
                workspaceId={workspaceId}
                baseUrl={baseUrl}
                formId={formId}
                onPendingChange={setPending}
                onBlockedChange={setBlocked}
                navigate={navigate}
              />
            )}
          </>
        ) : null}
      </>
    );
  }

  const canStart =
    template !== null && parsed !== null && !("error" in parsed) && ready && !blocked;

  return (
    <>
      <SheetHeader>
        <SheetTitle>{template ? `New run: ${template.name}` : "New run"}</SheetTitle>
        <SheetDescription>
          {template?.description ?? "Pick a template to start a run on your repository."}
        </SheetDescription>
      </SheetHeader>
      <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-4">{body}</div>
      <StartFooter
        formId={formId}
        canStart={canStart}
        pending={pending}
        onCancel={() => onOpenChange(false)}
      />
    </>
  );
}

function StartFooter({
  formId,
  canStart,
  pending,
  onCancel,
}: {
  formId: string;
  canStart: boolean;
  pending: boolean;
  onCancel: () => void;
}) {
  return (
    <SheetFooter className="flex-row justify-end gap-2">
      <Button type="button" variant="ghost" onClick={onCancel}>
        Cancel
      </Button>
      <Button type="submit" form={formId} disabled={!canStart || pending}>
        {pending ? (
          <LoaderCircleIcon
            aria-hidden="true"
            data-icon="inline-start"
            className="motion-safe:animate-spin"
          />
        ) : (
          <PlayIcon aria-hidden="true" data-icon="inline-start" />
        )}
        {pending ? "Starting…" : "Start run"}
      </Button>
    </SheetFooter>
  );
}

/**
 * Starts a run of a version of a stored workflow (5.7): the connections it needs, the repository
 * when its tools work on one, its input and a budget. Shaped as the New run sheet.
 */
export function WorkflowRunSheet({
  open,
  onOpenChange,
  ...props
}: WorkflowSheetProps & { open: boolean }) {
  const wide = useMediaQuery(MD_UP);
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side={wide ? "right" : "bottom"}
        className="data-[side=bottom]:h-svh"
        size="sm"
        data-testid="workflow-run-sheet"
      >
        <WorkflowSheetBody onOpenChange={onOpenChange} {...props} />
      </SheetContent>
    </Sheet>
  );
}

interface WorkflowSheetProps {
  onOpenChange: (open: boolean) => void;
  workflow: StoredWorkflowSource;
  workspaceId: string;
  baseUrl?: string;
  navigate?: (url: string) => void;
}

function WorkflowSheetBody({
  onOpenChange,
  workflow,
  workspaceId,
  baseUrl,
  navigate,
}: WorkflowSheetProps) {
  const readiness = useReadiness({ workspaceId, baseUrl });
  const formId = useId();
  const [pending, setPending] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const ready = isReady(readiness, workflow.requires);
  const returnTo = `/workflows/${encodeURIComponent(workflow.id)}?version=${workflow.version}`;
  return (
    <>
      <SheetHeader>
        <SheetTitle>New run: {workflow.name}</SheetTitle>
        <SheetDescription>
          Runs version {workflow.version} of <span className="font-mono">{workflow.id}</span>.
        </SheetDescription>
      </SheetHeader>
      <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-4">
        {workflow.requires.length > 0 ? (
          <ConnectionChecklist
            requires={workflow.requires}
            readiness={readiness}
            workspaceId={workspaceId}
            baseUrl={baseUrl}
            returnTo={returnTo}
            navigate={navigate}
          />
        ) : null}
        <NewRunForm
          source={{ workflow }}
          fields={NO_FIELDS}
          readiness={readiness}
          workspaceId={workspaceId}
          baseUrl={baseUrl}
          formId={formId}
          onPendingChange={setPending}
          onBlockedChange={setBlocked}
          navigate={navigate}
        />
      </div>
      <StartFooter
        formId={formId}
        canStart={ready && !blocked}
        pending={pending}
        onCancel={() => onOpenChange(false)}
      />
    </>
  );
}

const NO_FIELDS: FieldSpec[] = [];
