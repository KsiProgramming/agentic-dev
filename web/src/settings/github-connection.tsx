"use client";

import {
  ChevronDownIcon,
  CircleAlertIcon,
  CircleCheckIcon,
  ExternalLinkIcon,
  FolderGit2Icon,
  GitBranchIcon,
  LockIcon,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import {
  useConnections,
  useDisconnectGithub,
  useRepos,
  useStartGithubInstall,
  type Repo,
} from "@/api/queries";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { DEFAULT_WORKSPACE_ID } from "@/workspace";

import { ConfirmButton } from "./confirm-dialog";
import { ConnectionCard } from "./connection-card";

const PURPOSE = "Runs work on the repositories the platform's GitHub App is installed on.";

/** Messages for the `reason` the API's install redirect puts on `?github=error`. */
export const INSTALL_ERRORS: Record<string, string> = {
  state: "The install link expired or was already used. Try again.",
  installation: "GitHub did not confirm the installation. Try again.",
  pending: "An organisation owner must approve the install request on GitHub first.",
  github: "GitHub could not be reached. Try again.",
  not_configured: "The GitHub App is not configured on the API.",
};

export function installResult(
  result?: string,
  reason?: string,
): { ok: boolean; text: string } | null {
  if (result === "connected") return { ok: true, text: "GitHub App installed." };
  if (result === "error") {
    return { ok: false, text: INSTALL_ERRORS[reason ?? ""] ?? "The install did not complete." };
  }
  return null;
}

function RepoList({ repos }: { repos: Repo[] }) {
  const [open, setOpen] = useState(false);
  if (repos.length === 0) {
    return (
      <EmptyState
        icon={FolderGit2Icon}
        message="The installation has no repositories. Add some in its settings on GitHub."
      />
    );
  }
  const count = repos.length === 1 ? "1 repository" : `${repos.length} repositories`;
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <Button type="button" variant="ghost" size="sm" className="-ml-2">
          <ChevronDownIcon
            aria-hidden="true"
            data-icon="inline-start"
            className={open ? "rotate-180 transition-transform" : "transition-transform"}
          />
          {count} accessible
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ul className="mt-2 flex flex-col divide-y rounded-lg border" aria-label="Repositories">
          {repos.map((repo) => (
            <li key={repo.id} className="flex min-w-0 items-center gap-2 px-3 py-2">
              <a
                href={repo.html_url}
                target="_blank"
                rel="noreferrer"
                className="truncate font-mono underline-offset-4 hover:underline"
              >
                {repo.full_name}
              </a>
              {repo.private ? (
                <LockIcon
                  aria-label="Private"
                  className="size-3.5 shrink-0 text-muted-foreground"
                />
              ) : null}
              <span className="ml-auto flex shrink-0 items-center gap-1 font-mono text-xs text-muted-foreground">
                <GitBranchIcon aria-hidden="true" className="size-3" />
                {repo.default_branch}
              </span>
            </li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}

/** The GitHub connection card: links the workspace to the platform's GitHub App and lists the
 * repos it can reach. Installing happens on github.com, which sends the browser back here with
 * `?github=connected|error` (`result`, `reason`). */
export function GithubConnection({
  baseUrl,
  workspaceId = DEFAULT_WORKSPACE_ID,
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
  const connections = useConnections({ workspaceId, baseUrl });
  const repos = useRepos({ workspaceId, baseUrl });
  const install = useStartGithubInstall({ workspaceId, baseUrl, navigate });
  const disconnect = useDisconnectGithub({ workspaceId, baseUrl });
  const banner = installResult(result, reason);
  const github = connections.data?.find((c) => c.provider === "github") ?? null;

  const installButton = (label: string) => (
    <Button type="button" onClick={() => install.mutate(undefined)} disabled={install.isPending}>
      {label}
    </Button>
  );

  const card = (() => {
    const common = {
      icon: FolderGit2Icon,
      title: "GitHub",
      purpose: PURPOSE,
      testId: "github-card",
    };
    if (repos.isPending || connections.isPending) {
      return (
        <ConnectionCard {...common}>
          <LoadingState rows={2} label="Loading GitHub…" />
        </ConnectionCard>
      );
    }
    if (repos.isError) {
      return (
        <ConnectionCard {...common}>
          <ErrorState message={repos.error.message} onRetry={() => void repos.refetch()} />
        </ConnectionCard>
      );
    }
    switch (repos.data.state) {
      case "not-configured":
        return (
          <ConnectionCard
            {...common}
            status="unavailable"
            detail={
              <span data-testid="github-status" className="text-muted-foreground">
                The GitHub App is not configured on this server. {repos.data.detail}
              </span>
            }
          />
        );
      case "not-connected":
        return (
          <ConnectionCard
            {...common}
            status="missing"
            detail={
              <span data-testid="github-status" className="text-muted-foreground">
                Install the GitHub App on your account or organisation to pick repositories.
              </span>
            }
            actions={installButton("Install GitHub App")}
          />
        );
      case "gone":
        return (
          <ConnectionCard
            {...common}
            status="attention"
            detail={
              <span data-testid="github-status">
                The GitHub App was uninstalled
                {github?.account_login ? ` from ${github.account_login}` : ""} or lost access.
                Reconnect it to use your repositories again.
              </span>
            }
            actions={installButton("Reconnect")}
          />
        );
      case "connected":
        return (
          <ConnectionCard
            {...common}
            status="connected"
            detail={
              <span data-testid="github-status">
                Installed on{" "}
                <span className="font-medium">{github?.account_login ?? "GitHub"}</span>.
              </span>
            }
            actions={
              <>
                {github?.manage_url ? (
                  <Button asChild variant="outline">
                    <a href={github.manage_url} target="_blank" rel="noreferrer">
                      Manage on GitHub
                      <ExternalLinkIcon aria-hidden="true" data-icon="inline-end" />
                      <span className="sr-only">(opens in a new tab)</span>
                    </a>
                  </Button>
                ) : null}
                <ConfirmButton
                  label="Disconnect"
                  title="Disconnect GitHub?"
                  description="Runs can no longer use this installation's repositories. The App stays installed on GitHub."
                  confirmLabel="Disconnect"
                  disabled={disconnect.isPending}
                  onConfirm={() =>
                    disconnect.mutate(undefined, {
                      onSuccess: () => toast.success("GitHub disconnected."),
                    })
                  }
                />
              </>
            }
          >
            <RepoList repos={repos.data.repos} />
          </ConnectionCard>
        );
    }
  })();

  const error = install.error ?? disconnect.error;
  return (
    <div className="flex flex-col gap-3">
      {banner ? (
        <Alert
          role="status"
          variant={banner.ok ? "default" : "destructive"}
          data-testid="github-result"
        >
          {banner.ok ? (
            <CircleCheckIcon aria-hidden="true" className="text-status-succeeded" />
          ) : (
            <CircleAlertIcon aria-hidden="true" />
          )}
          <AlertDescription className={banner.ok ? "text-foreground" : undefined}>
            {banner.text}
          </AlertDescription>
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
