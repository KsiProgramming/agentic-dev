import { ArrowLeftIcon } from "lucide-react";
import Link from "next/link";
import { Suspense } from "react";

import { LoadingState } from "@/components/states";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ClaudeConnection } from "@/settings/claude-connection";
import { GithubConnection } from "@/settings/github-connection";

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
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6">
      <Link
        href="/"
        className="inline-flex items-center gap-1.5 self-start rounded-sm text-muted-foreground hover:text-foreground hover:underline"
      >
        <ArrowLeftIcon aria-hidden="true" className="size-4" />
        Back
      </Link>
      <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
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
    </main>
  );
}
