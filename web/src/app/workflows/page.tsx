import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState } from "@/components/states";
import { WorkflowsView } from "@/workflows/workflows-view";

export const metadata: Metadata = { title: "Workflows" };

/** The workspace's stored workflows (roadmap 5.8). `?blank=1` opens the new workflow sheet, so
 * the view renders on the client. */
export default function WorkflowsPage() {
  return (
    <Suspense fallback={<LoadingState rows={4} label="Loading workflows…" />}>
      <WorkflowsView />
    </Suspense>
  );
}
