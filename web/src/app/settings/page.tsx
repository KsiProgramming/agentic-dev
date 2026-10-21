import Link from "next/link";

import { ClaudeConnection } from "@/settings/claude-connection";

export default function SettingsPage() {
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
    </main>
  );
}
