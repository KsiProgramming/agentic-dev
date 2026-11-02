import {
  HistoryIcon,
  InboxIcon,
  LayoutTemplateIcon,
  ScrollTextIcon,
  SettingsIcon,
  WorkflowIcon,
  type LucideIcon,
} from "lucide-react";

import { shortId } from "@/components/display/short-id";
import { SETTINGS_PAGES } from "@/settings/pages";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

/** The sidebar's sections, in display order. Every page lives under one of them. */
export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/inbox", label: "Inbox", icon: InboxIcon },
  { href: "/runs", label: "Runs", icon: HistoryIcon },
  { href: "/workflows", label: "Workflows", icon: WorkflowIcon },
  { href: "/templates", label: "Templates", icon: LayoutTemplateIcon },
  { href: "/settings", label: "Settings", icon: SettingsIcon },
  { href: "/audit", label: "Audit log", icon: ScrollTextIcon },
];

/** Whether `href`'s section contains `pathname`: `/runs/abc` is under Runs, `/runsx` is not. */
export function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export interface Crumb {
  label: string;
  /** Absent on the current page. */
  href?: string;
  /** The full value when `label` is shortened (an id), shown as a tooltip. */
  title?: string;
  /** Ids and paths use the mono font. */
  mono?: boolean;
}

/** Ids longer than this are cut to their first 8 characters in breadcrumbs. */
const LONG_SEGMENT = 12;

/** Sections whose ids are readable slugs, shown in full (`Workflows › generate-docs`, 5.8). */
const READABLE_IDS: readonly string[] = ["/workflows"];

/** Breadcrumbs for a path: the section, then the item inside it, if any (`Runs › 1a2b3c4d`, or
 * `Settings › Integrations` for a settings sub-page). */
export function breadcrumbsFor(pathname: string): Crumb[] {
  const section = NAV_ITEMS.find((item) => isActive(pathname, item.href));
  if (!section) return [];
  const rest = pathname.slice(section.href.length + 1).split("/")[0];
  if (!rest) return [{ label: section.label }];
  const segment = decodeURIComponent(rest);
  const page = section.href === "/settings" && SETTINGS_PAGES.find((p) => p.segment === segment);
  if (page) return [{ label: section.label, href: section.href }, { label: page.label }];
  const readable = READABLE_IDS.includes(section.href);
  const short = !readable && segment.length > LONG_SEGMENT ? shortId(segment) : segment;
  return [
    { label: section.label, href: section.href },
    { label: short, title: short === segment ? undefined : segment, mono: true },
  ];
}
