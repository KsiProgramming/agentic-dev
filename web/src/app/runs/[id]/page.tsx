import { ArrowLeftIcon } from "lucide-react";
import Link from "next/link";
import { Suspense } from "react";

import { LoadingState } from "@/components/states";
import { RunEvents } from "@/runs/run-events";

async function RunEventsForParams({ params }: Pick<PageProps<"/runs/[id]">, "params">) {
  const { id } = await params;
  return <RunEvents key={id} runId={id} />;
}

export default function RunPage({ params }: PageProps<"/runs/[id]">) {
  return (
    <main className="mx-auto flex w-full max-w-5xl flex-col gap-4 px-4 py-6">
      <Link
        href="/"
        className="inline-flex items-center gap-1.5 self-start rounded-sm text-muted-foreground hover:text-foreground hover:underline"
      >
        <ArrowLeftIcon aria-hidden="true" className="size-4" />
        Start another run
      </Link>
      <Suspense fallback={<LoadingState label="Loading run…" />}>
        <RunEventsForParams params={params} />
      </Suspense>
    </main>
  );
}
