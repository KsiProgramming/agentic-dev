import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState } from "@/components/states";
import { ClaudeConnection } from "@/settings/claude-connection";
import { GithubConnection } from "@/settings/github-connection";
import { JiraConnection } from "@/settings/jira-connection";
import { SettingsSection } from "@/settings/settings-nav";

export const metadata: Metadata = { title: "Integrations · Settings" };

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** `github` and `reason` are set by the API when GitHub sends the browser back after an install,
 * `jira` and `reason` when Atlassian does after a consent. `reason` belongs to whichever of the
 * two came back. */
async function ConnectionsForSearchParams({
  searchParams,
}: Pick<PageProps<"/settings/integrations">, "searchParams">) {
  const query = await searchParams;
  const github = first(query.github);
  const jira = first(query.jira);
  const reason = first(query.reason);
  return (
    <>
      <GithubConnection result={github} reason={github ? reason : undefined} />
      <JiraConnection result={jira} reason={jira ? reason : undefined} />
    </>
  );
}

export default function IntegrationsPage({ searchParams }: PageProps<"/settings/integrations">) {
  return (
    <>
      <SettingsSection href="/settings/integrations" />
      <ClaudeConnection />
      <Suspense fallback={<LoadingState rows={2} />}>
        <ConnectionsForSearchParams searchParams={searchParams} />
      </Suspense>
    </>
  );
}
