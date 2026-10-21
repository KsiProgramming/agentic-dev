import Link from "next/link";

import { StartRunForm } from "@/runs/start-run-form";

export default function Home() {
  return (
    <main
      data-testid="app-root"
      className="flex min-h-screen flex-col items-center justify-center gap-6"
    >
      <h1 className="text-2xl font-semibold">Agentic Dev Platform</h1>
      <StartRunForm />
      <Link href="/settings" className="text-sm text-gray-500 hover:underline">
        Settings: Claude API key
      </Link>
    </main>
  );
}
