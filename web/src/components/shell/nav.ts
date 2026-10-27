import {
  HistoryIcon,
  LayoutTemplateIcon,
  ScrollTextIcon,
  SettingsIcon,
  type LucideIcon,
} from "lucide-react";

import { shortId } from "@/components/display/short-id";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

/** The sidebar's sections, in display order. Every page lives under one of them. */
export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/runs", label: "Runs", icon: HistoryIcon },
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

/** Breadcrumbs for a path: the section, then the item inside it, if any (`Runs › 1a2b3c4d`). */
export function breadcrumbsFor(pathname: string): Crumb[] {
  const section = NAV_ITEMS.find((item) => isActive(pathname, item.href));
  if (!section) return [];
  const rest = pathname.slice(section.href.length + 1).split("/")[0];
  if (!rest) return [{ label: section.label }];
  const segment = decodeURIComponent(rest);
  const short = segment.length > LONG_SEGMENT ? shortId(segment) : segment;
  return [
    { label: section.label, href: section.href },
    { label: short, title: short === segment ? undefined : segment, mono: true },
  ];
}
