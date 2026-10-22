"use client";

import { WorkflowIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { createApiClient } from "@/api/client";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

import { isActive, NAV_ITEMS } from "./nav";

type WorkspaceName = { state: "loading" } | { state: "ready"; name: string | null };

/** The current workspace's name. There is one workspace until there are users, so this is the
 * first one listed; on failure the name is simply left out. */
function useWorkspaceName(baseUrl?: string): WorkspaceName {
  const [loaded, setLoaded] = useState<WorkspaceName>({ state: "loading" });
  useEffect(() => {
    let live = true;
    createApiClient(baseUrl)
      .GET("/workspaces")
      .then(({ data }) => {
        if (live) setLoaded({ state: "ready", name: data?.[0]?.name ?? null });
      })
      .catch(() => {
        if (live) setLoaded({ state: "ready", name: null });
      });
    return () => {
      live = false;
    };
  }, [baseUrl]);
  return loaded;
}

interface NavLinksProps {
  rail: boolean;
  onNavigate?: () => void;
}

function CurrentNavLinks(props: NavLinksProps) {
  return <NavLinks pathname={usePathname()} {...props} />;
}

/** The main sections; the one containing `pathname` is marked current. */
function NavLinks({ pathname, rail, onNavigate }: NavLinksProps & { pathname: string | null }) {
  const railHidden = rail ? "lg:max-xl:sr-only" : undefined;
  return (
    <ul className="flex flex-col gap-0.5">
      {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
        const active = pathname !== null && isActive(pathname, href);
        const link = (
          <Link
            href={href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex h-9 items-center gap-2.5 rounded-md px-2.5 font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
              active && "bg-muted text-foreground",
              rail && "lg:max-xl:justify-center",
            )}
          >
            <Icon aria-hidden="true" className="size-4 shrink-0" />
            <span className={railHidden}>{label}</span>
          </Link>
        );
        return (
          <li key={href}>
            {rail ? (
              <Tooltip>
                <TooltipTrigger asChild>{link}</TooltipTrigger>
                {/* Only the rail needs a label on hover: the full sidebar shows it. */}
                <TooltipContent side="right" sideOffset={8} className="xl:hidden">
                  {label}
                </TooltipContent>
              </Tooltip>
            ) : (
              link
            )}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * The product name, the workspace and the main nav.
 *
 * `rail` makes it responsive: an icon rail with tooltips from `lg` to `xl` (1024–1279 px) and the
 * full sidebar from `xl`. Without it (the mobile drawer) it is always full.
 */
export function Sidebar({
  rail = false,
  onNavigate,
  baseUrl,
}: {
  rail?: boolean;
  onNavigate?: () => void;
  baseUrl?: string;
}) {
  const workspace = useWorkspaceName(baseUrl);
  // Hidden visually on the rail, still read by screen readers.
  const railHidden = rail ? "lg:max-xl:sr-only" : undefined;

  return (
    <div className="flex h-full flex-col gap-4 py-3">
      <div className={cn("flex items-center gap-2 px-4", rail && "lg:max-xl:justify-center")}>
        <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <WorkflowIcon aria-hidden="true" className="size-4" />
        </span>
        <div className={cn("flex min-w-0 flex-col", railHidden)}>
          <span className="font-semibold tracking-tight">Agentic Dev</span>
          {workspace.state === "loading" ? (
            <Skeleton aria-hidden="true" className="h-3.5 w-24" />
          ) : workspace.name ? (
            <span data-testid="workspace-name" className="truncate text-xs text-muted-foreground">
              {workspace.name}
            </span>
          ) : null}
        </div>
      </div>
      <nav aria-label="Main" className="px-2">
        {/* The path of a run (a dynamic param) is unknown while the shell prerenders: the
         * links render without the active mark until it is. */}
        <Suspense fallback={<NavLinks pathname={null} rail={rail} onNavigate={onNavigate} />}>
          <CurrentNavLinks rail={rail} onNavigate={onNavigate} />
        </Suspense>
      </nav>
    </div>
  );
}
