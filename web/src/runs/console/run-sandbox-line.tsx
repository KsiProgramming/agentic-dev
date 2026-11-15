"use client";

import { useQueryClient } from "@tanstack/react-query";
import { FileDiffIcon, PackageIcon, PackageXIcon, Trash2Icon } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { createApiClient } from "@/api/client";
import { ExpiresIn, RelativeTime } from "@/components/display";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";

import { runDetailKey, type RunDetail } from "../use-run-detail";
import { useNow } from "../use-now";
import { RunChangesSheet } from "./run-changes-sheet";

/**
 * What became of a failed or cancelled run's sandbox (12.3): kept until a time, with what the
 * writers changed and a way to remove it now, or removed, with what they changed still shown.
 * Nothing for a run whose sandbox is running, gone with a completed run, or that had none.
 * Once its time is up (or a removal was asked) it reads "being removed", and the run is read
 * again every 15 s until a worker has removed it.
 */
export function RunSandboxLine({
  runId,
  sandbox,
  baseUrl,
}: {
  runId: string;
  sandbox: RunDetail["sandbox"];
  baseUrl?: string;
}) {
  const [open, setOpen] = useState(false);
  const client = useQueryClient();
  const kept = sandbox.state === "kept";
  const now = useNow(15_000, kept);
  const due = kept && sandbox.kept_until != null && Date.parse(sandbox.kept_until) <= now;
  useEffect(() => {
    if (due) void client.invalidateQueries({ queryKey: runDetailKey(runId), exact: true });
  }, [client, due, now, runId]);
  if (!kept && sandbox.state !== "removed") return null;
  const Icon = kept ? PackageIcon : PackageXIcon;
  return (
    <div
      data-testid="run-sandbox"
      data-state={sandbox.state}
      className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border bg-card px-4 py-2 text-meta"
    >
      <Icon aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
      <p className="mr-auto flex min-w-0 flex-wrap items-center gap-x-2 text-foreground-secondary">
        {due ? (
          <span className="text-foreground">Sandbox being removed</span>
        ) : kept ? (
          <>
            <span className="text-foreground">Sandbox kept</span>
            {sandbox.kept_until ? <ExpiresIn iso={sandbox.kept_until} /> : null}
          </>
        ) : (
          <>
            <span className="text-foreground">Sandbox removed</span>
            {sandbox.removed_at ? <RelativeTime iso={sandbox.removed_at} /> : null}
            <span>· what the writers changed is still saved</span>
          </>
        )}
      </p>
      <Button type="button" variant="outline" size="sm" onClick={() => setOpen(true)}>
        <FileDiffIcon aria-hidden="true" data-icon="inline-start" />
        View changes
      </Button>
      {kept && !due ? <RemoveSandboxButton runId={runId} baseUrl={baseUrl} /> : null}
      <RunChangesSheet runId={runId} open={open} onOpenChange={setOpen} baseUrl={baseUrl} />
    </div>
  );
}

/** Asks for confirmation, then asks the API to remove the run's kept sandbox now; a worker
 * does within a minute, and the line then says it was removed. */
function RemoveSandboxButton({ runId, baseUrl }: { runId: string; baseUrl?: string }) {
  const client = useQueryClient();
  const [pending, setPending] = useState(false);
  const [sent, setSent] = useState(false);

  async function remove() {
    setPending(true);
    try {
      const { response } = await createApiClient(baseUrl).DELETE("/runs/{run_id}/sandbox", {
        params: { path: { run_id: runId } },
      });
      if (response.status === 202) {
        setSent(true);
        toast.success("Removing the sandbox. What the writers changed stays saved.");
        void client.invalidateQueries({ queryKey: runDetailKey(runId), exact: true });
      } else if (response.status === 409) {
        toast.error("The sandbox is already removed.");
      } else {
        toast.error(`The sandbox could not be removed (HTTP ${response.status}).`);
      }
    } catch {
      toast.error("Could not reach the API.");
    } finally {
      setPending(false);
    }
  }

  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button type="button" variant="outline" size="sm" disabled={pending || sent}>
          <Trash2Icon aria-hidden="true" data-icon="inline-start" />
          {sent ? "Removing…" : "Remove sandbox now"}
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Remove this run&apos;s sandbox now?</AlertDialogTitle>
          <AlertDialogDescription>
            Its container and files go within a minute, instead of when its time runs out. The
            commits its writers saved, and the files they changed, stay with the run.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Keep it</AlertDialogCancel>
          <AlertDialogAction variant="destructive" onClick={() => void remove()}>
            Remove sandbox
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
