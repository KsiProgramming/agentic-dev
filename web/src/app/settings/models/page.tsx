import type { Metadata } from "next";

import { ModelPricingCard } from "@/settings/model-pricing";
import { ProviderSettingsCard } from "@/settings/provider-settings";
import { SettingsSection } from "@/settings/settings-nav";

export const metadata: Metadata = { title: "Models and pricing · Settings" };

export default function ModelsPage() {
  return (
    <>
      <SettingsSection href="/settings/models" />
      <ProviderSettingsCard />
      <ModelPricingCard />
    </>
  );
}
