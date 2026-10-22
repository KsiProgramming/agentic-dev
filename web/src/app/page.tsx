import { SettingsIcon } from "lucide-react";
import Link from "next/link";

import { StartRunForm } from "@/runs/start-run-form";
import { DocsCard } from "@/templates/docs-card";

export default function Home() {
  return (
    <main data-testid="app-root" className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-8">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Agentic Dev Platform</h1>
        <p className="text-muted-foreground">
          Run AI agent workflows on your repositories. Every change lands as a pull request.
        </p>
      </header>
      <DocsCard />
      <StartRunForm />
      <Link
        href="/settings"
        className="inline-flex items-center gap-1.5 self-start rounded-sm text-muted-foreground hover:text-foreground hover:underline"
      >
        <SettingsIcon aria-hidden="true" className="size-4" />
        Settings: Claude API key and GitHub
      </Link>
    </main>
  );
}
