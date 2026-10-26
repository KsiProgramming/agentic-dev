import type { Metadata } from "next";
import { Suspense } from "react";

import { AuditView } from "@/audit/audit-view";
import { LoadingState } from "@/components/states";

export const metadata: Metadata = { title: "Audit log" };

/** The workspace's audit log (roadmap 3.7). Filters are read from the URL, so the view renders
 * on the client. */
export default function AuditPage() {
  return (
    <Suspense fallback={<LoadingState rows={6} label="Loading the audit log…" />}>
      <AuditView />
    </Suspense>
  );
}
