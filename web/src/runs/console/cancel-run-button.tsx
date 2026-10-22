"use client";

import { BanIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { createApiClient } from "@/api/client";
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

/** Asks for confirmation, then asks the API to cancel the run. The run's event stream shows when
 * the worker has stopped it. */
export function CancelRunButton({ runId, baseUrl }: { runId: string; baseUrl?: string }) {
  const [pending, setPending] = useState(false);
  const [sent, setSent] = useState(false);

  async function cancel() {
    setPending(true);
    try {
      const { response } = await createApiClient(baseUrl).POST("/runs/{run_id}/cancel", {
        params: { path: { run_id: runId } },
      });
      if (response.status === 202) {
        setSent(true);
        toast.success("Cancelling the run…");
      } else if (response.status === 409) {
        toast.error("The run has already ended.");
      } else {
        toast.error(`The run could not be cancelled (HTTP ${response.status}).`);
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
          <BanIcon aria-hidden="true" data-icon="inline-start" />
          {sent ? "Cancelling…" : "Cancel run"}
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Cancel this run?</AlertDialogTitle>
          <AlertDialogDescription>
            The run stops within a few seconds. What it already did stays in its history, and
            nothing is pushed or opened.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Keep running</AlertDialogCancel>
          <AlertDialogAction variant="destructive" onClick={() => void cancel()}>
            Cancel run
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
