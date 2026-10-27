import { GaugeIcon, PlugIcon, ReceiptIcon, type LucideIcon } from "lucide-react";

export interface SettingsPage {
  href: string;
  /** The last path segment, as breadcrumbs read it. */
  segment: string;
  label: string;
  description: string;
  icon: LucideIcon;
}

/** Settings' sub-pages, in the order its secondary nav lists them. `/settings` opens the first. */
export const SETTINGS_PAGES: readonly SettingsPage[] = [
  {
    href: "/settings/integrations",
    segment: "integrations",
    label: "Integrations",
    description: "The model access and the repositories this workspace works with.",
    icon: PlugIcon,
  },
  {
    href: "/settings/models",
    segment: "models",
    label: "Models and pricing",
    description: "What each model costs this workspace, per million tokens.",
    icon: ReceiptIcon,
  },
  {
    href: "/settings/limits",
    segment: "limits",
    label: "Limits and budgets",
    description: "How far this workspace's runs may go and what they may spend.",
    icon: GaugeIcon,
  },
];
