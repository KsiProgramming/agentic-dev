"use client";

import {
  ChevronDownIcon,
  CircleAlertIcon,
  CircleCheckIcon,
  ExternalLinkIcon,
  SquareKanbanIcon,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import {
  useDisconnectJira,
  useJira,
  useSetJiraSiteEnabled,
  useStartJiraAuthorize,
  type JiraConnection as JiraConnectionData,
  type JiraSite,
} from "@/api/queries";
import { ErrorState, LoadingState } from "@/components/states";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { useWorkspaceId } from "@/workspace";

import { ConfirmButton } from "./confirm-dialog";
import { ConnectionCard } from "./connection-card";
import { hasMappedFields, JiraFieldsSheet } from "./jira-fields-sheet";
import { JiraProjectsSheet } from "./jira-projects-sheet";

const PURPOSE = "Runs read Jira issues and, after an approval, comment on them and move them.";
/** Where a person removes the app's access for good; disconnecting here only forgets it. */
const ATLASSIAN_APPS_URL = "https://id.atlassian.com/manage-profile/apps";

/** Messages for the `reason` the API's callback puts on `?jira=error`. */
export const CONNECT_ERRORS: Record<string, string> = {
  state: "The connect link expired or was already used. Try again.",
  denied: "Access was not granted on Atlassian. Nothing was connected.",
  exchange: "Atlassian did not confirm the connection. Try again.",
  no_sites: "This Atlassian account reaches no Jira site. Connect with an account that does.",
  scopes: "Jira is connected, but a permission is missing. Reconnect and grant them all.",
  atlassian: "Atlassian could not be reached. Try again.",
  not_configured: "Jira is not configured on the API.",
};

/** Why a stored connection needs attention (`reason` of `GET /workspaces/{id}/jira`). */
const ATTENTION: Record<string, string> = {
  invalid_grant: "Atlassian refused to renew this connection. Reconnect to use Jira again.",
  unauthorized: "The app's access was removed on Atlassian. Reconnect to use Jira again.",
  scopes: "A permission the platform needs was not granted. Reconnect and grant them all.",
};

export function connectResult(
  result?: string,
  reason?: string,
): { ok: boolean; text: string } | null {
  if (result === "connected") return { ok: true, text: "Jira connected." };
  if (result === "error") {
    return { ok: false, text: CONNECT_ERRORS[reason ?? ""] ?? "Jira was not connected." };
  }
  return null;
}

/** A site's host, as a person knows it (`acme.atlassian.net`); the URL as given if it is not one. */
function host(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

function projectCount(site: JiraSite): string {
  if (site.projects.length === 0) return "No projects picked";
  return site.projects.length === 1 ? "1 project" : `${site.projects.length} projects`;
}

function SiteList({
  jira,
  workspaceId,
  baseUrl,
}: {
  jira: JiraConnectionData;
  workspaceId: string;
  baseUrl?: string;
}) {
  const [choosing, setChoosing] = useState<string | null>(null);
  const [mapping, setMapping] = useState<string | null>(null);
  const setEnabled = useSetJiraSiteEnabled({ workspaceId, baseUrl });
  const usable = jira.status === "connected";
  const sites = jira.sites ?? [];
  const site = sites.find((s) => s.cloud_id === choosing) ?? null;
  const mapped = sites.find((s) => s.cloud_id === mapping) ?? null;
  return (
    <>
      <ul
        className="flex flex-col divide-y divide-divider rounded-lg border"
        aria-label="Jira sites"
      >
        {sites.map((s) => (
          <li
            key={s.cloud_id}
            className="flex flex-col gap-2 px-3 py-2 sm:flex-row sm:items-center sm:justify-between"
          >
            {/* Site and project names come from Jira: shown as text. */}
            <div className="flex min-w-0 flex-col">
              <span className="truncate font-medium text-foreground">{s.name}</span>
              <span className="truncate font-mono text-caption text-foreground-secondary">
                {host(s.url)}
              </span>
              <span
                className="text-meta text-foreground-secondary"
                data-testid="jira-site-projects"
              >
                {s.enabled ? projectCount(s) : `Off · ${projectCount(s).toLowerCase()}`}
              </span>
              {s.projects.length > 0 ? (
                <ul
                  className="mt-1 flex flex-col gap-0.5"
                  aria-label={`Projects of ${s.name}`}
                  data-testid="jira-site-project-fields"
                >
                  {s.projects.map((p) => (
                    <li key={p.id} className="flex min-w-0 items-baseline gap-2 text-meta">
                      <span className="shrink-0 font-mono text-caption text-foreground-secondary">
                        {p.key}
                      </span>
                      <span className="truncate text-foreground-secondary">
                        {hasMappedFields(p) ? "Fields mapped" : "No fields mapped"}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
            {usable ? (
              <div className="flex flex-wrap gap-2 sm:shrink-0">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  aria-label={`Choose projects of ${s.name}`}
                  onClick={() => setChoosing(s.cloud_id)}
                >
                  Choose projects
                </Button>
                {s.projects.length > 0 ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    aria-label={`Map fields of ${s.name}`}
                    onClick={() => setMapping(s.cloud_id)}
                  >
                    Map fields
                  </Button>
                ) : null}
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  aria-label={`Turn ${s.enabled ? "off" : "on"} ${s.name}`}
                  aria-pressed={s.enabled}
                  disabled={setEnabled.isPending}
                  onClick={() => setEnabled.mutate({ cloudId: s.cloud_id, enabled: !s.enabled })}
                >
                  {s.enabled ? "Turn off" : "Turn on"}
                </Button>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
      {setEnabled.error ? (
        <Alert variant="destructive">
          <AlertDescription>{setEnabled.error.message}</AlertDescription>
        </Alert>
      ) : null}
      {site ? (
        <JiraProjectsSheet
          open
          site={site}
          workspaceId={workspaceId}
          baseUrl={baseUrl}
          onOpenChange={(open) => !open && setChoosing(null)}
        />
      ) : null}
      {mapped ? (
        <JiraFieldsSheet
          open
          site={mapped}
          workspaceId={workspaceId}
          baseUrl={baseUrl}
          onOpenChange={(open) => !open && setMapping(null)}
        />
      ) : null}
    </>
  );
}

function Permissions({ jira }: { jira: JiraConnectionData }) {
  const [open, setOpen] = useState(false);
  const granted = jira.scopes ?? [];
  const missing = jira.missing_scopes ?? [];
  if (granted.length === 0 && missing.length === 0) return null;
  const count = granted.length === 1 ? "1 permission" : `${granted.length} permissions`;
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <Button type="button" variant="ghost" size="sm" className="-ml-2">
          <ChevronDownIcon
            aria-hidden="true"
            data-icon="inline-start"
            className={open ? "rotate-180 transition-transform" : "transition-transform"}
          />
          {count} granted
          {missing.length > 0 ? `, ${missing.length} missing` : ""}
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ul className="mt-2 flex flex-col gap-1" aria-label="Permissions">
          {granted.map((scope) => (
            <li key={scope} className="font-mono text-caption text-foreground-secondary">
              {scope}
            </li>
          ))}
          {missing.map((scope) => (
            <li key={scope} className="font-mono text-caption text-status-waiting">
              {scope} (missing)
            </li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}

/** The Jira connection card (7.1): connects the workspace to an Atlassian account, lists the
 * sites it reaches and lets the user pick the projects runs may use on each. Consent happens on
 * atlassian.com, which sends the browser back here with `?jira=connected|error` (`result`,
 * `reason`). */
export function JiraConnection({
  baseUrl,
  workspaceId: givenWorkspaceId,
  result,
  reason,
  navigate,
}: {
  baseUrl?: string;
  workspaceId?: string;
  result?: string;
  reason?: string;
  navigate?: (url: string) => void;
}) {
  const workspaceId = useWorkspaceId(givenWorkspaceId);
  const jira = useJira({ workspaceId, baseUrl });
  const authorize = useStartJiraAuthorize({ workspaceId, baseUrl, navigate });
  const disconnect = useDisconnectJira({ workspaceId, baseUrl });
  const banner = connectResult(result, reason);

  const connectButton = (label: string) => (
    <Button
      type="button"
      onClick={() => authorize.mutate(undefined)}
      disabled={authorize.isPending}
    >
      {label}
    </Button>
  );
  const disconnectButton = (
    <ConfirmButton
      label="Disconnect"
      title="Disconnect Jira?"
      description={
        <>
          Runs can no longer use Jira, and the picked projects are forgotten. To remove the
          app&apos;s access as well, open{" "}
          <a
            href={ATLASSIAN_APPS_URL}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-foreground underline underline-offset-4"
          >
            your Atlassian account&apos;s connected apps
            <ExternalLinkIcon aria-hidden="true" className="size-3" />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
          .
        </>
      }
      confirmLabel="Disconnect"
      disabled={disconnect.isPending}
      onConfirm={() =>
        disconnect.mutate(undefined, { onSuccess: () => toast.success("Jira disconnected.") })
      }
    />
  );

  const card = (() => {
    const common = {
      icon: SquareKanbanIcon,
      title: "Jira",
      purpose: PURPOSE,
      testId: "jira-card",
    };
    if (jira.isPending) {
      return (
        <ConnectionCard {...common}>
          <LoadingState rows={2} label="Loading Jira…" />
        </ConnectionCard>
      );
    }
    if (jira.isError) {
      return (
        <ConnectionCard {...common}>
          <ErrorState message={jira.error.message} onRetry={() => void jira.refetch()} />
        </ConnectionCard>
      );
    }
    const data = jira.data;
    if (data.status === "not_connected") {
      return data.configured ? (
        <ConnectionCard
          {...common}
          status="missing"
          detail={
            <span data-testid="jira-status" className="text-muted-foreground">
              Connect a Jira Cloud account, then pick the projects runs may use.
            </span>
          }
          actions={connectButton("Connect Jira")}
        />
      ) : (
        <ConnectionCard
          {...common}
          status="unavailable"
          detail={
            <span data-testid="jira-status" className="text-muted-foreground">
              Jira is not configured on this server. Set the Atlassian OAuth app on the API.
            </span>
          }
        />
      );
    }
    const attention = data.status === "needs_attention";
    return (
      <ConnectionCard
        {...common}
        status={attention ? "attention" : "connected"}
        detail={
          <span data-testid="jira-status">
            {attention ? (
              (ATTENTION[data.reason ?? ""] ?? "Reconnect to use Jira again.")
            ) : (
              <>
                Connected as{" "}
                <span className="font-medium">{data.account ?? "an Atlassian account"}</span>. Jira
                shows this account as the author of what runs write.
              </>
            )}
          </span>
        }
        actions={
          <>
            {attention && data.configured ? connectButton("Reconnect") : null}
            {disconnectButton}
          </>
        }
      >
        <SiteList jira={data} workspaceId={workspaceId} baseUrl={baseUrl} />
        <Permissions jira={data} />
      </ConnectionCard>
    );
  })();

  const error = authorize.error ?? disconnect.error;
  return (
    <div className="flex flex-col gap-3">
      {banner ? (
        <Alert
          role="status"
          variant={banner.ok ? "default" : "destructive"}
          data-testid="jira-result"
        >
          {banner.ok ? (
            <CircleCheckIcon aria-hidden="true" className="text-status-succeeded" />
          ) : (
            <CircleAlertIcon aria-hidden="true" />
          )}
          <AlertDescription>{banner.text}</AlertDescription>
        </Alert>
      ) : null}
      {card}
      {error ? (
        <Alert variant="destructive">
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}
