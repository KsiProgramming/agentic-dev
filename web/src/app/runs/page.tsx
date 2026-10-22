import { HistoryIcon, LayoutTemplateIcon } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/states";
import { Button } from "@/components/ui/button";

export const metadata: Metadata = { title: "Runs" };

/** Run history arrives in roadmap 2.4; until then this page points at where runs start. */
export default function RunsPage() {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader title="Runs" description="Every run in this workspace, newest first." />
      <EmptyState
        icon={HistoryIcon}
        message="Run history is coming soon. Start a run from a template to follow it live."
        action={
          <Button asChild>
            <Link href="/templates">
              <LayoutTemplateIcon aria-hidden="true" data-icon="inline-start" />
              Browse templates
            </Link>
          </Button>
        }
      />
    </div>
  );
}
