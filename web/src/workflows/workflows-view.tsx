"use client";

import { PlusIcon, WorkflowIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { RelativeTime } from "@/components/display";
import { PageHeader } from "@/components/page-header";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useNow } from "@/runs/use-now";
import { useWorkspaceId } from "@/workspace";

import { useWorkflows, type WorkflowSummary } from "./api";
import { CompositeBadge } from "./composites";
import { NewWorkflowSheet } from "./new-workflow";

function href(workflow: WorkflowSummary): string {
  return `/workflows/${encodeURIComponent(workflow.workflow_id)}`;
}

function Name({ workflow }: { workflow: WorkflowSummary }) {
  return (
    <span className="flex min-w-0 flex-col">
      <span className="flex min-w-0 items-center gap-2">
        <Link href={href(workflow)} className="truncate font-medium hover:underline">
          {workflow.name}
        </Link>
        {workflow.published_version != null ? <CompositeBadge /> : null}
      </span>
      {workflow.description ? (
        <span className="line-clamp-2 text-caption text-foreground-secondary">
          {workflow.description}
        </span>
      ) : null}
    </span>
  );
}

/** The latest version, and a composite's latest published one (6.6) when it is older. */
function VersionText({ workflow }: { workflow: WorkflowSummary }) {
  const published = workflow.published_version;
  return (
    <span className="flex flex-col">
      <span>Version {workflow.latest_version}</span>
      {published != null && published !== workflow.latest_version ? (
        <span className="text-caption">Published {published}</span>
      ) : null}
    </span>
  );
}

function WorkflowsTable({ workflows, now }: { workflows: WorkflowSummary[]; now: number }) {
  return (
    <Table aria-label="Workflows">
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead className="w-64">Id</TableHead>
          <TableHead className="w-32">Version</TableHead>
          <TableHead className="w-32">Updated</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {workflows.map((workflow) => (
          <TableRow key={workflow.workflow_id} data-workflow-id={workflow.workflow_id}>
            <TableCell className="max-w-0 whitespace-normal">
              <Name workflow={workflow} />
            </TableCell>
            <TableCell className="max-w-64 truncate font-mono text-caption text-foreground-secondary">
              {workflow.workflow_id}
            </TableCell>
            <TableCell className="text-foreground-secondary">
              <VersionText workflow={workflow} />
            </TableCell>
            <TableCell className="text-foreground-secondary">
              <RelativeTime iso={workflow.updated_at} now={now} focusable={false} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function WorkflowCard({ workflow, now }: { workflow: WorkflowSummary; now: number }) {
  return (
    <Card size="sm" data-workflow-id={workflow.workflow_id} className="gap-1.5 px-3">
      <Name workflow={workflow} />
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-caption text-foreground-secondary">
        <span className="max-w-full truncate font-mono">{workflow.workflow_id}</span>
        <VersionText workflow={workflow} />
        <RelativeTime iso={workflow.updated_at} now={now} focusable={false} />
      </div>
    </Card>
  );
}

/**
 * The workspace's stored workflows (5.8), the most recently changed first: a table from `md`,
 * cards below. Each opens in the builder; "New workflow" (and `?blank=1`) opens the new
 * workflow sheet.
 */
export function WorkflowsView({
  baseUrl,
  workspaceId: givenWorkspaceId,
}: {
  baseUrl?: string;
  workspaceId?: string;
}) {
  const workspaceId = useWorkspaceId(givenWorkspaceId);
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const workflows = useWorkflows(workspaceId, true, baseUrl);
  const items = workflows.data ?? [];
  const now = useNow(60_000, items.length > 0);
  const blank = searchParams.get("blank") === "1";
  const openBlank = () => router.replace(`${pathname}?blank=1`, { scroll: false });
  const closeBlank = () => router.replace(pathname, { scroll: false });

  const newWorkflow = (
    <Button type="button" onClick={openBlank}>
      <PlusIcon aria-hidden="true" data-icon="inline-start" />
      New workflow
    </Button>
  );

  return (
    <div className="flex w-full flex-col gap-6">
      <PageHeader
        title="Workflows"
        description="Workflows stored in this workspace. Open one to edit, compare versions or run it."
        actions={items.length > 0 ? newWorkflow : undefined}
      />
      {workflows.isPending ? (
        <LoadingState rows={4} label="Loading workflows…" />
      ) : workflows.isError ? (
        <ErrorState message={workflows.error.message} onRetry={() => void workflows.refetch()} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={WorkflowIcon}
          message="No workflows yet."
          description="Start from a blank canvas, or open a template in the builder."
          action={newWorkflow}
        />
      ) : (
        <>
          <div className="hidden md:block">
            <WorkflowsTable workflows={items} now={now} />
          </div>
          <ul aria-label="Workflows" className="flex flex-col gap-2 md:hidden">
            {items.map((workflow) => (
              <li key={workflow.workflow_id}>
                <WorkflowCard workflow={workflow} now={now} />
              </li>
            ))}
          </ul>
        </>
      )}
      <NewWorkflowSheet
        open={blank}
        onOpenChange={(next) => (next ? undefined : closeBlank())}
        workspaceId={workspaceId}
        baseUrl={baseUrl}
      />
    </div>
  );
}
