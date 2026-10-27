import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState } from "@/components/states";
import { InboxView } from "@/inbox/inbox-view";

export const metadata: Metadata = { title: "Inbox" };

/** The gates waiting for a decision (roadmap 11.5). The selection is read from the URL, so the
 * view renders on the client. */
export default function InboxPage() {
  return (
    <Suspense fallback={<LoadingState rows={4} label="Loading the Inbox…" />}>
      <InboxView />
    </Suspense>
  );
}
