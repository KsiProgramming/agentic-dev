"use client";

import { PlusIcon, ZapIcon } from "lucide-react";
import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";
import { toast } from "sonner";

import {
  useDeleteJiraTrigger,
  useJira,
  useJiraTriggers,
  usePatchJiraTrigger,
  useTemplates,
  type JiraConnection,
  type JiraTrigger,
} from "@/api/queries";
import { IdChip, RelativeTime } from "@/components/display";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { repoLabel } from "@/runs/summaries";
import { useWorkspaceId } from "@/workspace";

import { ConfirmButton } from "./confirm-dialog";
import { ConnectionCard } from "./connection-card";
import { JiraTriggerSheet } from "./jira-trigger-sheet";
import { fireBadge, ruleTarget, ruleWhen, webhookProblem } from "./trigger-text";

const PURPOSE =
  "Start a run when a Jira issue moves to a status or gets a label. Every write the run makes still waits for an approval.";

/** The site's name as the connection lists it, else its cloud id. */
function siteName(jira: JiraConnection, cloudId: string): string {
  return jira.sites?.find((s) => s.cloud_id === cloudId)?.name ?? cloudId;
}

/** Whether Jira can reach the workspace's triggers, site by site (7.3): listening, or why not. */
function Listening({ jira }: { jira: JiraConnection }) {
  const webhooks = (jira.webhooks ?? []).filter((w) => w.state !== "not_needed");
  if (webhooks.length === 0) return null;
  return (
    <ul className="flex flex-col gap-2" aria-label="Jira sites listening">
      {webhooks.map((webhook) => (
        <li
          key={webhook.cloud_id}
          className="flex flex-col gap-1 text-meta sm:flex-row sm:items-center sm:gap-3"
          data-testid="jira-listening"
        >
          {/* Site names come from Jira: shown as text. */}
          <span className="font-medium text-foreground">{siteName(jira, webhook.cloud_id)}</span>
          {webhook.state === "listening" ? (
            <>
              <StatusBadge status="succeeded" label="Listening" />
              {webhook.renewed_at ? (
                <span className="text-foreground-secondary">
                  <RelativeTime iso={webhook.renewed_at} prefix="Renewed " />
                </span>
              ) : null}
            </>
          ) : (
            <>
              <StatusBadge status="failed" label="Not listening" />
              <span className="text-foreground-secondary">{webhookProblem(webhook)}</span>
            </>
          )}
        </li>
      ))}
    </ul>
  );
}

/** "When an issue in API moves to In Progress". Keys and values come from people and Jira:
 * shown as text. */
function RuleSentence({ rule }: { rule: JiraTrigger }) {
  return (
    <span className="text-foreground">
      When an issue in <span className="font-mono text-caption">{rule.project_key}</span>{" "}
      {rule.on === "status" ? "moves to " : "gets the label "}
      <span className="font-medium">{rule.value}</span>
    </span>
  );
}

function Target({ rule, names }: { rule: JiraTrigger; names: ReadonlyMap<string, string> }) {
  return (
    <span className="flex min-w-0 flex-col">
      <span className="truncate font-medium text-foreground">{ruleTarget(rule, names)}</span>
      {rule.repo ? (
        <span className="truncate font-mono text-caption text-foreground-secondary">
          {repoLabel(rule.repo.url)}
          {rule.repo.ref ? ` › ${rule.repo.ref}` : ""}
        </span>
      ) : null}
    </span>
  );
}

function LastFire({ rule }: { rule: JiraTrigger }) {
  const last = rule.last;
  if (!last) return <span className="text-muted-foreground">Not fired yet</span>;
  const badge = fireBadge(last.outcome);
  return (
    <span className="flex flex-col items-start gap-1">
      <StatusBadge status={badge.status} label={badge.label} />
      <span className="flex flex-wrap items-center gap-1.5 text-caption text-foreground-secondary">
        <span className="font-mono">{last.issue_key}</span>
        <RelativeTime iso={last.at} focusable={false} />
        {last.run_id ? (
          <IdChip id={last.run_id} label="run" href={`/runs/${last.run_id}`} focusable={false} />
        ) : null}
      </span>
      {last.reason ? (
        <span className="text-caption text-foreground-secondary">{last.reason}</span>
      ) : null}
    </span>
  );
}

function RuleActions({
  rule,
  workspaceId,
  baseUrl,
}: {
  rule: JiraTrigger;
  workspaceId: string;
  baseUrl?: string;
}) {
  const patch = usePatchJiraTrigger({ workspaceId, baseUrl });
  const remove = useDeleteJiraTrigger({ workspaceId, baseUrl });
  const sentence = `${rule.project_key} ${ruleWhen(rule)}`;
  return (
    <div className="flex flex-col items-end gap-1">
      <div className="flex gap-2">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-pressed={rule.enabled}
          aria-label={`${rule.enabled ? "Turn off" : "Turn on"} the trigger: ${sentence}`}
          disabled={patch.isPending}
          onClick={() => patch.mutate({ triggerId: rule.id, patch: { enabled: !rule.enabled } })}
        >
          {rule.enabled ? "Turn off" : "Turn on"}
        </Button>
        <ConfirmButton
          label="Delete"
          ariaLabel={`Delete the trigger: ${sentence}`}
          title="Delete this trigger?"
          description="Issues that move no longer start runs from it. The runs it started stay."
          confirmLabel="Delete"
          disabled={remove.isPending}
          onConfirm={() =>
            remove.mutate(rule.id, { onSuccess: () => toast.success("Trigger deleted.") })
          }
        />
      </div>
      {(patch.error ?? remove.error) ? (
        <span role="alert" className="text-caption text-status-failed">
          {(patch.error ?? remove.error)?.message}
        </span>
      ) : null}
    </div>
  );
}

function Rules({
  rules,
  names,
  workspaceId,
  baseUrl,
}: {
  rules: JiraTrigger[];
  names: ReadonlyMap<string, string>;
  workspaceId: string;
  baseUrl?: string;
}) {
  return (
    <>
      {/* A table where the card is 720 px or wider, a card per rule below (by the card's width). */}
      <div className="hidden @min-[720px]:block">
        <Table aria-label="Jira triggers">
          <TableHeader>
            <TableRow>
              <TableHead>Trigger</TableHead>
              <TableHead>Runs</TableHead>
              <TableHead>Last</TableHead>
              <TableHead>
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rules.map((rule) => (
              <TableRow
                key={rule.id}
                data-testid="jira-trigger"
                data-enabled={rule.enabled}
                className="align-top"
              >
                <TableCell className="whitespace-normal">
                  <RuleSentence rule={rule} />
                  {rule.enabled ? null : (
                    <span className="block text-caption text-muted-foreground">Off</span>
                  )}
                </TableCell>
                <TableCell className="max-w-64 whitespace-normal">
                  <Target rule={rule} names={names} />
                </TableCell>
                <TableCell className="whitespace-normal">
                  <LastFire rule={rule} />
                </TableCell>
                <TableCell>
                  <RuleActions rule={rule} workspaceId={workspaceId} baseUrl={baseUrl} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <ul aria-label="Jira triggers" className="flex flex-col gap-2 @min-[720px]:hidden">
        {rules.map((rule) => (
          <li
            key={rule.id}
            data-testid="jira-trigger"
            data-enabled={rule.enabled}
            className="flex flex-col gap-3 rounded-lg border p-3 text-meta"
          >
            <div className="flex flex-col gap-1">
              <RuleSentence rule={rule} />
              {rule.enabled ? null : (
                <span className="text-caption text-muted-foreground">Off</span>
              )}
            </div>
            <Target rule={rule} names={names} />
            <LastFire rule={rule} />
            <RuleActions rule={rule} workspaceId={workspaceId} baseUrl={baseUrl} />
          </li>
        ))}
      </ul>
    </>
  );
}

/** Settings › Triggers (7.3): the workspace's Jira trigger rules, whether Jira can reach them,
 * and the sheet that adds one. */
export function JiraTriggers({
  baseUrl,
  workspaceId: givenWorkspaceId,
}: {
  baseUrl?: string;
  workspaceId?: string;
}) {
  const workspaceId = useWorkspaceId(givenWorkspaceId);
  const jira = useJira({ workspaceId, baseUrl });
  const connected = jira.data?.status === "connected";
  const triggers = useJiraTriggers({ workspaceId, baseUrl, enabled: connected });
  const templates = useTemplates({ baseUrl });
  const [adding, setAdding] = useState(false);
  const names = useMemo(
    () => new Map((templates.data ?? []).map((t) => [t.id, t.name])),
    [templates.data],
  );

  const card = (children: ReactNode, action?: ReactNode) => (
    <ConnectionCard
      icon={ZapIcon}
      title="Jira triggers"
      purpose={PURPOSE}
      testId="jira-triggers-card"
      actions={action}
    >
      {children}
    </ConnectionCard>
  );

  if (jira.isPending) return card(<LoadingState rows={2} label="Loading the triggers…" />);
  if (jira.isError) {
    return card(<ErrorState message={jira.error.message} onRetry={() => void jira.refetch()} />);
  }
  if (!connected) {
    return card(
      <EmptyState
        icon={ZapIcon}
        message="Connect Jira to start runs from its issues."
        description={
          jira.data.status === "needs_attention"
            ? "The Jira connection needs attention. Reconnect it first."
            : "Triggers watch the projects you pick on a Jira site."
        }
        action={
          <Button asChild>
            <Link href="/settings/integrations">Open Integrations</Link>
          </Button>
        }
      />,
    );
  }

  const sites = (jira.data.sites ?? []).filter((s) => s.enabled && s.projects.length > 0);
  const addButton = (
    <Button
      type="button"
      onClick={() => setAdding(true)}
      disabled={sites.length === 0}
      aria-describedby={sites.length === 0 ? "jira-triggers-no-projects" : undefined}
    >
      <PlusIcon aria-hidden="true" data-icon="inline-start" />
      New trigger
    </Button>
  );

  const body = (() => {
    if (triggers.isPending) return <LoadingState rows={3} label="Loading the triggers…" />;
    if (triggers.isError) {
      return (
        <ErrorState message={triggers.error.message} onRetry={() => void triggers.refetch()} />
      );
    }
    if (triggers.data.length === 0) {
      return (
        <EmptyState
          icon={ZapIcon}
          message="No trigger yet."
          description="Add one to start a run when an issue moves, without opening this app."
        />
      );
    }
    return (
      <Rules rules={triggers.data} names={names} workspaceId={workspaceId} baseUrl={baseUrl} />
    );
  })();

  return card(
    <>
      {sites.length === 0 ? (
        <Alert id="jira-triggers-no-projects">
          <AlertDescription>
            Pick projects on a Jira site in{" "}
            <Link href="/settings/integrations" className="text-foreground underline">
              Integrations
            </Link>{" "}
            before adding a trigger.
          </AlertDescription>
        </Alert>
      ) : null}
      <Listening jira={jira.data} />
      {body}
      <JiraTriggerSheet
        open={adding}
        sites={sites}
        workspaceId={workspaceId}
        baseUrl={baseUrl}
        onOpenChange={setAdding}
      />
    </>,
    addButton,
  );
}
