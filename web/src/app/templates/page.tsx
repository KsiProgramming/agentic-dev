import type { Metadata } from "next";

import { PageHeader } from "@/components/page-header";
import { StartRunForm } from "@/runs/start-run-form";
import { DocsCard } from "@/templates/docs-card";

export const metadata: Metadata = { title: "Templates" };

export default function TemplatesPage() {
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6">
      <PageHeader
        title="Templates"
        description="Run AI agent workflows on your repositories. Every change lands as a pull request."
      />
      <DocsCard />
      <StartRunForm />
    </div>
  );
}
