import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState } from "@/components/states";
import { ClaudeConnection } from "@/settings/claude-connection";
import { GithubConnection } from "@/settings/github-connection";
import { SettingsSection } from "@/settings/settings-nav";

export const metadata: Metadata = { title: "Integrations · Settings" };

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** `github` and `reason` are set by the API when GitHub sends the browser back after an install. */
async function GithubForSearchParams({
  searchParams,
}: Pick<PageProps<"/settings/integrations">, "searchParams">) {
  const query = await searchParams;
  return <GithubConnection result={first(query.github)} reason={first(query.reason)} />;
}

export default function IntegrationsPage({ searchParams }: PageProps<"/settings/integrations">) {
  return (
    <>
      <SettingsSection href="/settings/integrations" />
      <ClaudeConnection />
      <Suspense fallback={<LoadingState rows={2} />}>
        <GithubForSearchParams searchParams={searchParams} />
      </Suspense>
    </>
  );
}
