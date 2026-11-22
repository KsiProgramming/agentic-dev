"use client";

import { CircleAlertIcon, CircleCheckIcon, UserRoundIcon } from "lucide-react";
import { toast } from "sonner";

import {
  useDeleteGithubUser,
  useGithubUser,
  useStartGithubUserAuthorize,
  type GithubUserConnection as GithubUserConnectionData,
} from "@/api/queries";
import { RelativeTime } from "@/components/display";
import { ErrorState, LoadingState } from "@/components/states";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useWorkspaceId } from "@/workspace";

import { ConfirmButton } from "./confirm-dialog";
import { ConnectionBadge, ConnectionCard } from "./connection-card";

const PURPOSE =
  "Runs that use GitHub Copilot run on the Copilot subscription of the person who starts them. This is separate from the company's GitHub connection, which stays for repositories and pull requests.";

/** Messages for the `reason` the API's callback puts on `?github_user=error`. */
export const CONNECT_ERRORS: Record<string, string> = {
  state: "The connect link expired or was already used. Try again.",
  denied: "Access was not granted on GitHub. Nothing was connected.",
  exchange: "GitHub did not confirm the connection. Try again.",
  github: "GitHub could not be reached. Try again.",
  not_configured: "Personal GitHub accounts are not configured on the API.",
};

/** Why a stored connection needs attention (`reason` of `GET /workspaces/{id}/github-user`). */
const ATTENTION: Record<string, string> = {
  invalid_grant: "GitHub refused this connection. Reconnect to run on this Copilot again.",
  unauthorized:
    "This account's access was removed on GitHub. Reconnect to run on its Copilot again.",
};

/** A sentence for why a connection needs attention. */
export function attentionText(reason?: string | null): string {
  return ATTENTION[reason ?? ""] ?? "Reconnect to run on this Copilot again.";
}

export function connectResult(
  result?: string,
  reason?: string,
): { ok: boolean; text: string } | null {
  if (result === "connected") return { ok: true, text: "GitHub account connected." };
  if (result === "error") {
    return {
      ok: false,
      text: CONNECT_ERRORS[reason ?? ""] ?? "The GitHub account was not connected.",
    };
  }
  return null;
}

function Accounts({
  connections,
  onReconnect,
  onRemove,
  busy,
}: {
  connections: GithubUserConnectionData[];
  onReconnect: () => void;
  onRemove: (connection: GithubUserConnectionData) => void;
  busy: boolean;
}) {
  return (
    <ul
      className="flex flex-col divide-y divide-divider rounded-lg border"
      aria-label="Connected GitHub accounts"
    >
      {connections.map((c) => {
        const attention = c.status === "needs_attention";
        return (
          <li
            key={c.id}
            className="flex flex-col gap-2 px-3 py-2 sm:flex-row sm:items-center sm:justify-between"
          >
            <div className="flex min-w-0 flex-col gap-1">
              <div className="flex flex-wrap items-center gap-2">
                {/* The login comes from GitHub: shown as text. */}
                <span className="truncate font-mono font-medium text-foreground">{c.login}</span>
                <ConnectionBadge status={attention ? "attention" : "connected"} />
              </div>
              {attention ? (
                <span className="text-meta text-foreground-secondary">
                  {attentionText(c.reason)}
                </span>
              ) : null}
              <span className="text-meta text-foreground-secondary">
                <RelativeTime iso={c.connected_at} prefix="Connected " />
              </span>
            </div>
            <div className="flex flex-wrap gap-2 sm:shrink-0">
              {attention ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  aria-label={`Reconnect ${c.login}`}
                  disabled={busy}
                  onClick={onReconnect}
                >
                  Reconnect
                </Button>
              ) : null}
              <ConfirmButton
                label="Remove"
                ariaLabel={`Remove ${c.login}`}
                title={`Remove ${c.login}?`}
                description="Runs can no longer use this account's Copilot, and its stored access is deleted. Runs already started keep going. To revoke the app on GitHub as well, open your GitHub settings under Applications."
                confirmLabel="Remove"
                disabled={busy}
                onConfirm={() => onRemove(c)}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/** The personal GitHub connection card (8.2): each person connects their own GitHub account so a
 * run can use their Copilot. GitHub sends the browser back here with
 * `?github_user=connected|error` (`result`, `reason`). */
export function GithubUserConnection({
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
  const accounts = useGithubUser({ workspaceId, baseUrl });
  const authorize = useStartGithubUserAuthorize({ workspaceId, baseUrl, navigate });
  const remove = useDeleteGithubUser({ workspaceId, baseUrl });
  const banner = connectResult(result, reason);

  const connectButton = (label: string, variant: "default" | "outline" = "default") => (
    <Button
      type="button"
      variant={variant}
      onClick={() => authorize.mutate(undefined)}
      disabled={authorize.isPending}
    >
      {label}
    </Button>
  );

  const card = (() => {
    const common = {
      icon: UserRoundIcon,
      title: "GitHub (personal, for Copilot)",
      purpose: PURPOSE,
      testId: "github-user-card",
    };
    if (accounts.isPending) {
      return (
        <ConnectionCard {...common}>
          <LoadingState rows={2} label="Loading GitHub accounts…" />
        </ConnectionCard>
      );
    }
    if (accounts.isError) {
      return (
        <ConnectionCard {...common}>
          <ErrorState message={accounts.error.message} onRetry={() => void accounts.refetch()} />
        </ConnectionCard>
      );
    }
    const { configured, connections } = accounts.data;
    if (!configured) {
      return (
        <ConnectionCard
          {...common}
          status="unavailable"
          detail={
            <span data-testid="github-user-status" className="text-muted-foreground">
              Personal GitHub accounts are not set up on this server. Add the GitHub OAuth app to
              the API to use Copilot.
            </span>
          }
        />
      );
    }
    if (connections.length === 0) {
      return (
        <ConnectionCard
          {...common}
          status="missing"
          detail={
            <span data-testid="github-user-status" className="text-muted-foreground">
              Connect your GitHub account to run on your own Copilot. Nothing here reads a
              repository or opens a pull request.
            </span>
          }
          actions={connectButton("Connect your GitHub account")}
        />
      );
    }
    const usable = connections.some((c) => c.status === "connected");
    return (
      <ConnectionCard
        {...common}
        status={usable ? "connected" : "attention"}
        actions={connectButton("Connect another account", "outline")}
      >
        <Accounts
          connections={connections}
          busy={remove.isPending || authorize.isPending}
          onReconnect={() => authorize.mutate(undefined)}
          onRemove={(c) =>
            remove.mutate(c.id, { onSuccess: () => toast.success(`${c.login} removed.`) })
          }
        />
      </ConnectionCard>
    );
  })();

  const error = authorize.error ?? remove.error;
  return (
    <div className="flex flex-col gap-3">
      {banner ? (
        <Alert
          role="status"
          variant={banner.ok ? "default" : "destructive"}
          data-testid="github-user-result"
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
