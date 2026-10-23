import type { Metadata } from "next";
import { Suspense } from "react";

import { PageHeader } from "@/components/page-header";
import { LoadingState } from "@/components/states";
import { ClaudeConnection } from "@/settings/claude-connection";
import { GithubConnection } from "@/settings/github-connection";
import { ModelPricingCard } from "@/settings/model-pricing";
import { RunLimitsCard } from "@/settings/run-limits";

export const metadata: Metadata = { title: "Settings" };

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** `github` and `reason` are set by the API when GitHub sends the browser back after an install. */
async function GithubForSearchParams({
  searchParams,
}: Pick<PageProps<"/settings">, "searchParams">) {
  const query = await searchParams;
  return <GithubConnection result={first(query.github)} reason={first(query.reason)} />;
}

export default function SettingsPage({ searchParams }: PageProps<"/settings">) {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      <PageHeader
        title="Settings"
        description="Model access, the repositories this workspace can work on, what its runs cost and how far they may go."
      />
      <ClaudeConnection />
      <Suspense fallback={<LoadingState rows={2} />}>
        <GithubForSearchParams searchParams={searchParams} />
      </Suspense>
      <ModelPricingCard />
      <RunLimitsCard />
    </div>
  );
}
