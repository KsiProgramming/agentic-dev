"use client";

import { SparklesIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { useConnections, useRemoveClaudeKey } from "@/api/queries";
import { ErrorState, LoadingState } from "@/components/states";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { DEFAULT_WORKSPACE_ID } from "@/workspace";

import { ClaudeKeyForm } from "./claude-key-form";
import { ConfirmButton } from "./confirm-dialog";
import { ConnectionCard } from "./connection-card";

const PURPOSE = "Agents run on Claude with this workspace's API key.";

/** The Claude connection card: stores, replaces or removes the workspace's API key. The key is
 * write only: once saved, only its last 4 characters are shown. */
export function ClaudeConnection({
  baseUrl,
  workspaceId = DEFAULT_WORKSPACE_ID,
}: {
  baseUrl?: string;
  workspaceId?: string;
}) {
  const connections = useConnections({ workspaceId, baseUrl });
  const remove = useRemoveClaudeKey({ workspaceId, baseUrl });
  const [replacing, setReplacing] = useState(false);

  if (connections.isPending) {
    return (
      <ConnectionCard icon={SparklesIcon} title="Claude" purpose={PURPOSE} testId="claude-card">
        <LoadingState rows={2} label="Loading the Claude connection…" />
      </ConnectionCard>
    );
  }
  if (connections.isError) {
    return (
      <ConnectionCard icon={SparklesIcon} title="Claude" purpose={PURPOSE} testId="claude-card">
        <ErrorState
          message={connections.error.message}
          onRetry={() => void connections.refetch()}
        />
      </ConnectionCard>
    );
  }

  const connection = connections.data.find((c) => c.provider === "claude") ?? null;
  if (connection === null) {
    return (
      <ConnectionCard
        icon={SparklesIcon}
        title="Claude"
        purpose={PURPOSE}
        status="missing"
        detail={<span className="text-muted-foreground">Runs fail until a key is saved.</span>}
        testId="claude-card"
      >
        <ClaudeKeyForm workspaceId={workspaceId} baseUrl={baseUrl} />
      </ConnectionCard>
    );
  }

  return (
    <ConnectionCard
      icon={SparklesIcon}
      title="Claude"
      purpose={PURPOSE}
      status="connected"
      detail={
        <span data-testid="claude-status">
          Key ending in <span className="font-mono">…{connection.key_hint}</span>, updated{" "}
          {new Date(connection.updated_at).toLocaleString()}.
        </span>
      }
      actions={
        replacing ? null : (
          <>
            <Button type="button" variant="outline" onClick={() => setReplacing(true)}>
              Replace key
            </Button>
            <ConfirmButton
              label="Remove key"
              title="Remove the Claude key?"
              description="Runs on Claude fail until a new key is saved."
              confirmLabel="Remove key"
              disabled={remove.isPending}
              onConfirm={() =>
                remove.mutate(undefined, {
                  onSuccess: () => toast.success("Claude key removed."),
                })
              }
            />
          </>
        )
      }
      testId="claude-card"
    >
      {replacing ? (
        <ClaudeKeyForm
          workspaceId={workspaceId}
          baseUrl={baseUrl}
          submitLabel="Replace key"
          onSaved={() => setReplacing(false)}
          onCancel={() => setReplacing(false)}
        />
      ) : null}
      {remove.isError ? (
        <Alert variant="destructive">
          <AlertDescription>{remove.error.message}</AlertDescription>
        </Alert>
      ) : null}
    </ConnectionCard>
  );
}
