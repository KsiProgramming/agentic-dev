import type { Metadata } from "next";

import { RunLimitsCard } from "@/settings/run-limits";
import { SettingsSection } from "@/settings/settings-nav";

export const metadata: Metadata = { title: "Limits and budgets · Settings" };

export default function LimitsPage() {
  return (
    <>
      <SettingsSection href="/settings/limits" />
      <RunLimitsCard />
    </>
  );
}
