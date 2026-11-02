"use client";

import { CircleAlertIcon, CircleCheckIcon } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";

import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { NewRunSheet } from "@/runs/new-run/new-run-sheet";
import { useReadiness } from "@/runs/new-run/readiness";
import { installResult } from "@/settings/github-connection";
import { useWorkflowFromTemplate } from "@/workflows/api";
import { useWorkspaceId } from "@/workspace";

import { TemplateGallery } from "./template-gallery";

/**
 * The start screen: the template gallery, and the "New run" sheet of the template named by
 * `?template=`. GitHub's install comes back here with `&github=connected|error` when it was
 * started from the sheet.
 */
export function TemplatesView({
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
  const readiness = useReadiness({ workspaceId, baseUrl });
  const templateId = searchParams.get("template");
  const banner = installResult(
    searchParams.get("github") ?? undefined,
    searchParams.get("reason") ?? undefined,
  );

  const open = (id: string) =>
    router.replace(`${pathname}?template=${encodeURIComponent(id)}`, { scroll: false });
  const close = () => router.replace(pathname, { scroll: false });
  const fromTemplate = useWorkflowFromTemplate(workspaceId, baseUrl);
  const edit = (id: string) =>
    fromTemplate.mutate(id, {
      onSuccess: (workflowId) => router.push(`/workflows/${encodeURIComponent(workflowId)}`),
      onError: (err) => toast.error(err.message),
    });

  return (
    <div className="flex w-full flex-col gap-6">
      <PageHeader
        title="Start a run"
        description="Pick a template. Every change lands as a pull request you review."
      />
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
          <AlertDescription>{banner.text}</AlertDescription>
        </Alert>
      ) : null}
      <TemplateGallery
        readiness={readiness}
        onStart={open}
        onEdit={edit}
        editing={fromTemplate.isPending ? (fromTemplate.variables ?? null) : null}
        baseUrl={baseUrl}
      />
      <NewRunSheet
        open={templateId !== null}
        onOpenChange={(next) => (next ? undefined : close())}
        templateId={templateId}
        workspaceId={workspaceId}
        baseUrl={baseUrl}
      />
    </div>
  );
}
