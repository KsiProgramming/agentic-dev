"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { isActive } from "@/components/shell/nav";
import { cn } from "@/lib/utils";

import { SETTINGS_PAGES } from "./pages";

/** Settings' secondary nav: a list beside the page from `md`, a row of links above it below
 * that (scrolling in its own box if it must). */
export function SettingsNav() {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Settings"
      className="-mx-1 overflow-x-auto px-1 md:mx-0 md:overflow-visible md:px-0"
    >
      <ul className="flex gap-1 border-b md:flex-col md:gap-0.5 md:border-b-0">
        {SETTINGS_PAGES.map(({ href, label, icon: Icon }) => {
          const active = isActive(pathname, href);
          return (
            <li key={href} className="shrink-0">
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex h-9 items-center gap-2.5 px-2.5 font-medium whitespace-nowrap text-muted-foreground transition-colors hover:text-foreground",
                  // Tabs below `md` (an underline), a list item from `md` (a filled row).
                  "-mb-px border-b-2 border-transparent md:mb-0 md:rounded-md md:border-b-0 md:hover:bg-muted",
                  active && "border-primary text-foreground md:bg-muted",
                )}
              >
                <Icon aria-hidden="true" className="size-4 shrink-0" />
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/** A settings sub-page's title and one line on what it holds, under the page's own header. */
export function SettingsSection({ href }: { href: string }) {
  const page = SETTINGS_PAGES.find((p) => p.href === href);
  if (!page) return null;
  return (
    <div className="flex flex-col gap-1">
      <h2 className="text-section font-semibold">{page.label}</h2>
      <p className="max-w-prose text-muted-foreground">{page.description}</p>
    </div>
  );
}
