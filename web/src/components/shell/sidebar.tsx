"use client";

import { WorkflowIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { createApiClient } from "@/api/client";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useWorkspaceId } from "@/workspace";

import { countLabel, useWaitingCount } from "./attention";
import { isActive, NAV_ITEMS } from "./nav";

type WorkspaceName = { state: "loading" } | { state: "ready"; name: string | null };

/** The current workspace's name (`useWorkspaceId`); on failure the name is simply left out. */
function useWorkspaceName(baseUrl?: string): WorkspaceName {
  const workspaceId = useWorkspaceId();
  const [loaded, setLoaded] = useState<WorkspaceName>({ state: "loading" });
  useEffect(() => {
    let live = true;
    createApiClient(baseUrl)
      .GET("/workspaces")
      .then(({ data }) => {
        const name = data?.find((w) => w.id === workspaceId)?.name ?? null;
        if (live) setLoaded({ state: "ready", name });
      })
      .catch(() => {
        if (live) setLoaded({ state: "ready", name: null });
      });
    return () => {
      live = false;
    };
  }, [baseUrl, workspaceId]);
  return loaded;
}

interface NavLinksProps {
  rail: boolean;
  onNavigate?: () => void;
}

function CurrentNavLinks(props: NavLinksProps) {
  return <NavLinks pathname={usePathname()} {...props} />;
}

/** The gates waiting for a decision, on "Inbox": a count, or a dot on the icon rail. */
function WaitingBadge({ count, rail }: { count: number; rail: boolean }) {
  if (count === 0) return null;
  const text = `${countLabel(count)} ${count === 1 ? "needs" : "need"} approval`;
  return (
    <>
      <span
        aria-hidden="true"
        data-testid="inbox-waiting-badge"
        className={cn(
          "ml-auto flex h-5 min-w-5 items-center justify-center rounded-full bg-status-waiting-muted px-1.5 text-xs font-semibold text-status-waiting tabular-nums",
          rail &&
            "lg:max-xl:absolute lg:max-xl:top-1 lg:max-xl:right-1 lg:max-xl:h-2 lg:max-xl:min-w-2 lg:max-xl:bg-status-waiting lg:max-xl:p-0 lg:max-xl:text-[0px]",
        )}
      >
        {countLabel(count)}
      </span>
      <span className="sr-only">, {text}</span>
    </>
  );
}

/** The main sections; the one containing `pathname` is marked current. */
function NavLinks({ pathname, rail, onNavigate }: NavLinksProps & { pathname: string | null }) {
  const railHidden = rail ? "lg:max-xl:sr-only" : undefined;
  const waiting = useWaitingCount();
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
              "relative flex h-9 items-center gap-2.5 rounded-md px-2.5 font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
              active && "bg-muted text-foreground",
              rail && "lg:max-xl:justify-center",
            )}
          >
            <Icon aria-hidden="true" className="size-4 shrink-0" />
            <span className={railHidden}>{label}</span>
            {href === "/inbox" ? <WaitingBadge count={waiting} rail={rail} /> : null}
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
