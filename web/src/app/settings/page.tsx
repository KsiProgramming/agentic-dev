import type { Metadata } from "next";
import { Suspense } from "react";

import { PageHeader } from "@/components/page-header";
import { LoadingState } from "@/components/states";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ClaudeConnection } from "@/settings/claude-connection";
import { GithubConnection } from "@/settings/github-connection";

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
        description="Model access and the repositories this workspace can work on."
      />
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Claude</h2>
          </CardTitle>
          <CardDescription>
            Runs on Claude use this key. It is stored encrypted and never shown again.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ClaudeConnection />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>GitHub</h2>
          </CardTitle>
          <CardDescription>
            Runs work on the repos the platform&apos;s GitHub App is installed on.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Suspense fallback={<LoadingState rows={2} />}>
            <GithubForSearchParams searchParams={searchParams} />
          </Suspense>
        </CardContent>
      </Card>
    </div>
  );
}
