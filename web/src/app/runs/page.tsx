import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState } from "@/components/states";
import { RunsView } from "@/runs/runs-view";

export const metadata: Metadata = { title: "Runs" };

/** The home page: every run of the workspace (roadmap 2.4). Filters are read from the URL, so
 * the view renders on the client. */
export default function RunsPage() {
  return (
    <Suspense fallback={<LoadingState rows={5} label="Loading runs…" />}>
      <RunsView />
    </Suspense>
  );
}
