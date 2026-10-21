import Link from "next/link";
import { Suspense } from "react";

import { RunEvents } from "@/runs/run-events";

async function RunEventsForParams({ params }: Pick<PageProps<"/runs/[id]">, "params">) {
  const { id } = await params;
  return <RunEvents key={id} runId={id} />;
}

export default function RunPage({ params }: PageProps<"/runs/[id]">) {
  return (
    <main className="mx-auto max-w-5xl p-6">
      <Link href="/" className="text-sm text-gray-500 hover:underline">
        ← Start another run
      </Link>
      <Suspense fallback={<p className="mt-4 text-gray-500">Loading run…</p>}>
        <RunEventsForParams params={params} />
      </Suspense>
    </main>
  );
}
