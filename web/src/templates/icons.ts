import {
  FileTextIcon,
  LayoutTemplateIcon,
  ScanSearchIcon,
  UsersIcon,
  type LucideIcon,
} from "lucide-react";

/** Icons for the templates we know; others (and runs with no template) get a generic one. */
const ICONS: Record<string, LucideIcon> = {
  "generate-docs": FileTextIcon,
  "audit-codebase": ScanSearchIcon,
  "plan-build-review": UsersIcon,
};

/** The icon of template `id`: on its gallery card and in the header of its runs. */
export function templateIcon(id: string | null | undefined): LucideIcon {
  return (id ? ICONS[id] : undefined) ?? LayoutTemplateIcon;
}
