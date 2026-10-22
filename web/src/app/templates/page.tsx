import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState } from "@/components/states";
import { TemplatesView } from "@/templates/templates-view";

export const metadata: Metadata = { title: "Templates" };

/** The start screen: the template gallery and its "New run" sheet (`?template=<id>`). */
export default function TemplatesPage() {
  return (
    <Suspense fallback={<LoadingState rows={4} label="Loading templates…" />}>
      <TemplatesView />
    </Suspense>
  );
}
