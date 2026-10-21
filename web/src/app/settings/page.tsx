import Link from "next/link";
import { Suspense } from "react";

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
    <main className="mx-auto flex max-w-5xl flex-col gap-6 p-6">
      <Link href="/" className="text-sm text-gray-500 hover:underline">
        ← Back
      </Link>
      <h1 className="text-2xl font-semibold">Settings</h1>
      <section className="flex flex-col gap-2">
        <h2 className="text-lg font-medium">Claude</h2>
        <p className="text-sm text-gray-600">
          Runs on Claude use this key. It is stored encrypted and never shown again.
        </p>
        <ClaudeConnection />
      </section>
      <section className="flex flex-col gap-2">
        <h2 className="text-lg font-medium">GitHub</h2>
        <p className="text-sm text-gray-600">
          Runs work on the repos the platform&apos;s GitHub App is installed on.
        </p>
        <Suspense fallback={<p className="text-sm text-gray-500">Loading…</p>}>
          <GithubForSearchParams searchParams={searchParams} />
        </Suspense>
      </section>
    </main>
  );
}
