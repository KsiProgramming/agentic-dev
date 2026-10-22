import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState } from "@/components/states";
import { RunEvents } from "@/runs/run-events";

export async function generateMetadata({ params }: PageProps<"/runs/[id]">): Promise<Metadata> {
  const { id } = await params;
  return { title: `Run ${id.slice(0, 8)}` };
}

async function RunEventsForParams({ params }: Pick<PageProps<"/runs/[id]">, "params">) {
  const { id } = await params;
  return <RunEvents key={id} runId={id} />;
}

/** The run's own header (id and live status) is its page header until the console redesign (2.5). */
export default function RunPage({ params }: PageProps<"/runs/[id]">) {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
      <Suspense fallback={<LoadingState label="Loading run…" />}>
        <RunEventsForParams params={params} />
      </Suspense>
    </div>
  );
}
