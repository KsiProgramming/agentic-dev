import type { Metadata } from "next";

import { JiraTriggers } from "@/settings/jira-triggers";
import { SettingsSection } from "@/settings/settings-nav";

export const metadata: Metadata = { title: "Triggers · Settings" };

export default function TriggersPage() {
  return (
    <>
      <SettingsSection href="/settings/triggers" />
      <JiraTriggers />
    </>
  );
}
