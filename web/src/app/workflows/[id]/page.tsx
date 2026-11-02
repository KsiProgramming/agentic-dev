import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState } from "@/components/states";
import { WorkflowBuilder } from "@/workflows/builder";

export async function generateMetadata({
  params,
}: PageProps<"/workflows/[id]">): Promise<Metadata> {
  const { id } = await params;
  return { title: `Workflow ${decodeURIComponent(id)}` };
}

async function BuilderForParams({ params }: Pick<PageProps<"/workflows/[id]">, "params">) {
  const { id } = await params;
  const workflowId = decodeURIComponent(id);
  return <WorkflowBuilder key={workflowId} workflowId={workflowId} />;
}

export default function WorkflowPage({ params }: PageProps<"/workflows/[id]">) {
  return (
    <div className="flex w-full flex-col gap-4">
      <Suspense fallback={<LoadingState label="Loading workflow…" />}>
        <BuilderForParams params={params} />
      </Suspense>
    </div>
  );
}
