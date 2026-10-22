import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState } from "@/components/states";
import { RunConsole } from "@/runs/console/run-console";

export async function generateMetadata({ params }: PageProps<"/runs/[id]">): Promise<Metadata> {
  const { id } = await params;
  return { title: `Run ${id.slice(0, 8)}` };
}

async function RunConsoleForParams({ params }: Pick<PageProps<"/runs/[id]">, "params">) {
  const { id } = await params;
  return <RunConsole key={id} runId={id} />;
}

export default function RunPage({ params }: PageProps<"/runs/[id]">) {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
      <Suspense fallback={<LoadingState label="Loading run…" />}>
        <RunConsoleForParams params={params} />
      </Suspense>
    </div>
  );
}
