import Link from "next/link";

import { ClaudeConnection } from "@/settings/claude-connection";
import { GithubConnection } from "@/settings/github-connection";

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function SettingsPage({ searchParams }: PageProps<"/settings">) {
  // Set by the API when GitHub sends the browser back after installing the App.
  const query = await searchParams;
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
        <GithubConnection result={first(query.github)} reason={first(query.reason)} />
      </section>
    </main>
  );
}
