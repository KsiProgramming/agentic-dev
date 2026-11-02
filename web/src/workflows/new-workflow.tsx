"use client";

import { FolderGit2Icon, LoaderCircleIcon, PlusIcon, SparklesIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useId, useState, type FormEvent, type ReactNode } from "react";

import { ApiError, validationIssues } from "@/api/errors";
import type { Requirement } from "@/api/queries";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { FieldMessage } from "@/forms/schema-form/schema-fields";
import { MD_UP, useMediaQuery } from "@/lib/use-media-query";
import { ConnectionChip } from "@/runs/new-run/connection-chip";
import { REQUIREMENT_LABEL, useReadiness, type Readiness } from "@/runs/new-run/readiness";

import { useCreateBlankWorkflow, type BlankWorkflow } from "./api";
import { useNodeTypes, type NodeManifest } from "./node-types";

/** A workflow id: the engine's `NodeId`, as it names branches and URLs. */
export const WORKFLOW_ID = /^[a-z][a-z0-9_-]{0,62}$/;

/** The id a name gives, as the engine's `workflow_slug` makes it (`schemas/fixtures/
 * workflow-slugs.json` keeps the two alike): ASCII only, lower case, every run of other
 * characters a `-`, `w-` in front unless it starts with a letter, at most 63 characters. */
export function slugify(name: string): string {
  const ascii = name.normalize("NFKD").replace(/[^\p{ASCII}]/gu, "");
  const slug =
    ascii
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "workflow";
  const prefixed = /^[a-z]/.test(slug) ? slug : `w-${slug}`;
  return prefixed.slice(0, 63).replace(/-+$/, "");
}

/** The providers an agent may run on: the agent manifest's `provider` choices (5.8). */
export function agentProviders(manifests: NodeManifest[]): string[] {
  const agent = manifests.find((m) => m.kind === "agent");
  const properties = agent?.parameters.properties;
  if (!properties || typeof properties !== "object") return [];
  const provider = (properties as Record<string, { enum?: unknown }>).provider;
  return Array.isArray(provider?.enum)
    ? provider.enum.filter((v): v is string => typeof v === "string")
    : [];
}

const PROVIDER_ICONS: Record<string, typeof SparklesIcon> = { claude: SparklesIcon };

function providerLabel(provider: string): string {
  return provider in REQUIREMENT_LABEL ? REQUIREMENT_LABEL[provider as Requirement] : provider;
}

type FieldName = "name" | "id" | "description" | "provider";
type Errors = Partial<Record<FieldName, ReactNode>>;

/**
 * Starts a workflow from a blank canvas (5.8): its name, id, description and the provider its
 * first agent runs on, then the builder. A side sheet from 768 px, a full-height bottom sheet
 * below, like the New run sheet.
 */
export function NewWorkflowSheet({
  open,
  onOpenChange,
  workspaceId,
  baseUrl,
  navigate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceId: string;
  baseUrl?: string;
  navigate?: (url: string) => void;
}) {
  const wide = useMediaQuery(MD_UP);
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side={wide ? "right" : "bottom"}
        className="data-[side=bottom]:h-svh"
        size="sm"
        data-testid="new-workflow-sheet"
      >
        {/* Mounted only while open, so a closed sheet asks the API for nothing. */}
        <SheetBody
          onCancel={() => onOpenChange(false)}
          workspaceId={workspaceId}
          baseUrl={baseUrl}
          navigate={navigate}
        />
      </SheetContent>
    </Sheet>
  );
}

function SheetBody({
  onCancel,
  workspaceId,
  baseUrl,
  navigate,
}: {
  onCancel: () => void;
  workspaceId: string;
  baseUrl?: string;
  navigate?: (url: string) => void;
}) {
  const router = useRouter();
  const formId = useId();
  const nameId = useId();
  const idId = useId();
  const descriptionId = useId();
  const readiness = useReadiness({ workspaceId, baseUrl });
  const nodeTypes = useNodeTypes(baseUrl);
  const create = useCreateBlankWorkflow(workspaceId, baseUrl);
  const [name, setName] = useState("");
  // The id follows the name until it is edited.
  const [ownId, setOwnId] = useState<string | null>(null);
  const [description, setDescription] = useState("");
  const [chosen, setChosen] = useState<string | null>(null);
  const [errors, setErrors] = useState<Errors>({});
  const [rootError, setRootError] = useState<string | null>(null);

  const id = ownId ?? (name.trim() ? slugify(name) : "");
  const providers = nodeTypes.data ? agentProviders(nodeTypes.data) : [];
  const provider = chosen ?? providers[0] ?? null;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const found: Errors = {};
    if (!name.trim()) found.name = "Give the workflow a name.";
    if (!WORKFLOW_ID.test(id)) {
      found.id = "Use lower-case letters, digits, - and _, starting with a letter.";
    }
    setErrors(found);
    setRootError(null);
    if (Object.keys(found).length > 0) return;
    const blank: BlankWorkflow = { name: name.trim(), id };
    if (description.trim()) blank.description = description.trim();
    if (provider) blank.provider = provider as BlankWorkflow["provider"];
    try {
      const version = await create.mutateAsync(blank);
      const url = `/workflows/${encodeURIComponent(version.workflow_id)}?node=agent_1`;
      if (navigate) navigate(url);
      else router.push(url);
    } catch (err) {
      showRefusal(err);
    }
  }

  function showRefusal(err: unknown) {
    if (err instanceof ApiError && err.code === "workflow_exists") {
      setErrors({
        id: (
          <>
            A workflow with this id exists.{" "}
            <Link href={`/workflows/${encodeURIComponent(id)}`} className="underline">
              Open it
            </Link>
          </>
        ),
      });
      return;
    }
    if (err instanceof ApiError) {
      const onFields: Errors = {};
      for (const issue of validationIssues(err.body)) {
        const field = issue.loc.at(-1);
        if (field === "name" || field === "id" || field === "description" || field === "provider") {
          onFields[field] = issue.msg;
        }
      }
      if (Object.keys(onFields).length > 0) {
        setErrors(onFields);
        return;
      }
    }
    setRootError(err instanceof Error ? err.message : String(err));
  }

  const pending = create.isPending;
  return (
    <>
      <SheetHeader>
        <SheetTitle>New workflow</SheetTitle>
        <SheetDescription>
          A blank canvas with one agent step. Add, move and configure steps in the builder.
        </SheetDescription>
      </SheetHeader>
      <form
        id={formId}
        onSubmit={(e) => void onSubmit(e)}
        noValidate
        className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-4"
      >
        <Field data-invalid={errors.name ? true : undefined}>
          <FieldLabel htmlFor={nameId}>Name</FieldLabel>
          <Input
            id={nameId}
            value={name}
            autoComplete="off"
            placeholder="Release notes"
            aria-invalid={errors.name ? true : undefined}
            aria-describedby={errors.name ? `${nameId}-error` : undefined}
            disabled={pending}
            onChange={(e) => setName(e.target.value)}
          />
          {errors.name ? <FieldMessage id={`${nameId}-error`}>{errors.name}</FieldMessage> : null}
        </Field>
        <Field data-invalid={errors.id ? true : undefined}>
          <FieldLabel htmlFor={idId}>Id</FieldLabel>
          <Input
            id={idId}
            value={id}
            autoComplete="off"
            spellCheck={false}
            className="font-mono"
            placeholder="release-notes"
            aria-invalid={errors.id ? true : undefined}
            aria-describedby={errors.id ? `${idId}-error` : `${idId}-help`}
            disabled={pending}
            onChange={(e) => setOwnId(e.target.value)}
          />
          {errors.id ? (
            <FieldMessage id={`${idId}-error`}>{errors.id}</FieldMessage>
          ) : (
            <FieldDescription id={`${idId}-help`}>
              In its address and branch names. Lower-case letters, digits, - and _.
            </FieldDescription>
          )}
        </Field>
        <Field data-invalid={errors.description ? true : undefined}>
          <FieldLabel htmlFor={descriptionId}>Description (optional)</FieldLabel>
          <Textarea
            id={descriptionId}
            rows={3}
            value={description}
            aria-invalid={errors.description ? true : undefined}
            aria-describedby={errors.description ? `${descriptionId}-error` : undefined}
            disabled={pending}
            onChange={(e) => setDescription(e.target.value)}
          />
          {errors.description ? (
            <FieldMessage id={`${descriptionId}-error`}>{errors.description}</FieldMessage>
          ) : null}
        </Field>
        <ProviderPicker
          providers={providers}
          loading={nodeTypes.isPending}
          failed={nodeTypes.isError}
          onRetry={() => void nodeTypes.refetch()}
          value={provider}
          onChange={setChosen}
          readiness={readiness}
          error={errors.provider}
          disabled={pending}
        />
        {rootError ? (
          <Alert variant="destructive">
            <AlertDescription>{rootError}</AlertDescription>
          </Alert>
        ) : null}
      </form>
      <SheetFooter className="flex-row justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" form={formId} disabled={pending}>
          {pending ? (
            <LoaderCircleIcon
              aria-hidden="true"
              data-icon="inline-start"
              className="motion-safe:animate-spin"
            />
          ) : (
            <PlusIcon aria-hidden="true" data-icon="inline-start" />
          )}
          {pending ? "Creating…" : "Create workflow"}
        </Button>
      </SheetFooter>
    </>
  );
}

/** The provider the starter agent runs on: one radio per provider the engine has, with whether
 * it is connected, and GitHub Copilot, which is not available yet (Milestone 8). */
function ProviderPicker({
  providers,
  loading,
  failed,
  onRetry,
  value,
  onChange,
  readiness,
  error,
  disabled,
}: {
  providers: string[];
  loading: boolean;
  failed: boolean;
  onRetry: () => void;
  value: string | null;
  onChange: (provider: string) => void;
  readiness: Readiness;
  error?: ReactNode;
  disabled: boolean;
}) {
  const name = useId();
  const state = value && value in readiness.state ? readiness.state[value as Requirement] : null;
  return (
    <fieldset
      className="flex flex-col gap-2"
      aria-describedby={error ? `${name}-error` : `${name}-help`}
    >
      <legend className="mb-2 text-meta font-medium">Provider</legend>
      {loading ? (
        <Skeleton className="h-14 rounded-lg" aria-label="Loading providers…" />
      ) : failed ? (
        <Alert variant="destructive">
          <AlertDescription className="flex flex-wrap items-center gap-2">
            Could not load the providers.
            <Button type="button" variant="outline" size="sm" onClick={onRetry}>
              Retry
            </Button>
          </AlertDescription>
        </Alert>
      ) : (
        providers.map((p) => {
          const Icon = PROVIDER_ICONS[p] ?? SparklesIcon;
          const connection = p in readiness.state ? readiness.state[p as Requirement] : null;
          return (
            <label
              key={p}
              className="flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2.5 hover:bg-muted has-checked:border-primary has-checked:bg-surface-subtle"
            >
              <input
                type="radio"
                name={name}
                value={p}
                checked={value === p}
                disabled={disabled}
                onChange={() => onChange(p)}
                className="size-4"
              />
              <Icon aria-hidden="true" className="size-4" />
              <span className="flex-1 font-medium">{providerLabel(p)}</span>
              {connection ? <ConnectionChip state={connection} /> : null}
            </label>
          );
        })
      )}
      <label className="flex items-center gap-3 rounded-lg border px-3 py-2.5 text-placeholder">
        <input type="radio" name={name} value="copilot" disabled className="size-4" />
        <FolderGit2Icon aria-hidden="true" className="size-4" />
        <span className="flex flex-1 flex-col">
          <span className="font-medium">GitHub Copilot</span>
          <span className="text-caption">Comes with the Copilot adapter.</span>
        </span>
      </label>
      {error ? (
        <FieldMessage id={`${name}-error`}>{error}</FieldMessage>
      ) : state && state !== "ready" && state !== "loading" ? (
        <FieldDescription id={`${name}-help`}>
          {providerLabel(value ?? "")} is not connected. Connect it before you run the workflow:{" "}
          <Link href="/settings/integrations" className="text-foreground underline">
            Integrations
          </Link>
          .
        </FieldDescription>
      ) : (
        <FieldDescription id={`${name}-help`}>
          The first agent runs on it. Each step can change it in the builder.
        </FieldDescription>
      )}
    </fieldset>
  );
}
