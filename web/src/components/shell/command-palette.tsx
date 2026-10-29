"use client";

import {
  AlertCircleIcon,
  CheckCircleIcon,
  ExternalLinkIcon,
  LoaderCircleIcon,
  MoonIcon,
  PlusIcon,
  SearchIcon,
  type LucideIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useEffect, useState, type Dispatch, type SetStateAction } from "react";

import { apiBaseUrl } from "@/api/client";
import { IdChip } from "@/components/display";
import { shortId } from "@/components/display/short-id";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { inboxRuns, useWaitingRuns } from "@/inbox/waiting";
import { SETTINGS_PAGES } from "@/settings/pages";
import { badgeStatus, expiredLabel, repoLabel, type RunSummary } from "@/runs/summaries";
import { useRunSearch } from "@/runs/use-run-search";
import { useWorkspaceId } from "@/workspace";

import { useClientNow } from "./attention";
import { NAV_ITEMS } from "./nav";

const FULL_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const PR_NUMBER = /\/pull\/(\d+)$/;

/** How long the palette waits after a keystroke before it searches. */
const DEBOUNCE_MS = 200;

function useDebounced(value: string, ms: number): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return debounced;
}

/** `⌘K` / `Ctrl+K` opens or closes the palette from anywhere, except inside the diff editor,
 * whose own shortcuts start with `Ctrl+K`. */
export function usePaletteShortcut(setOpen: Dispatch<SetStateAction<boolean>>) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() !== "k" || !(event.metaKey || event.ctrlKey)) return;
      if (event.altKey || event.shiftKey || event.defaultPrevented) return;
      if (event.target instanceof Element && event.target.closest(".monaco-editor")) return;
      event.preventDefault();
      setOpen((open) => !open);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [setOpen]);
}

/** The top bar's way into the palette: a search field look-alike from `md`, an icon below. */
export function PaletteButton({ onClick }: { onClick: () => void }) {
  return (
    <Button
      type="button"
      variant="outline"
      onClick={onClick}
      aria-label="Search runs and commands"
      aria-keyshortcuts="Meta+K Control+K"
      className="size-8 border-border-strong p-0 font-normal text-placeholder md:w-60 md:justify-start md:px-2.5"
    >
      <SearchIcon aria-hidden="true" />
      {/* The name starts with the visible text, "Search" (WCAG 2.5.3): the ellipsis is drawn by
          CSS, as is the shortcut (in `aria-keyshortcuts`), so neither is visible text. */}
      <span className="hidden after:content-['…'] md:inline">Search</span>
      <kbd
        aria-hidden="true"
        className="ml-auto hidden rounded-sm border px-1 font-sans text-kbd font-medium text-muted-foreground after:content-['⌘K'] md:inline"
      />
    </Button>
  );
}

interface PaletteCommand {
  id: string;
  label: string;
  icon: LucideIcon;
  href?: string;
  run?: () => void;
}

function matches(label: string, query: string): boolean {
  return query === "" || label.toLowerCase().includes(query.toLowerCase());
}

function RunRow({ run }: { run: RunSummary }) {
  const pr = run.pr_url ? PR_NUMBER.exec(run.pr_url)?.[1] : undefined;
  return (
    <>
      <StatusBadge status={badgeStatus(run.status)} label={expiredLabel(run)} />
      <span className="min-w-0 truncate">{run.workflow.name}</span>
      <IdChip id={run.id} focusable={false} className="text-muted-foreground" />
      <span className="ml-auto hidden min-w-0 items-center gap-2 text-meta text-muted-foreground sm:flex">
        {run.repo ? <span className="truncate font-mono">{repoLabel(run.repo.url)}</span> : null}
        {pr ? <span className="tabular-nums">#{pr}</span> : null}
      </span>
    </>
  );
}

/**
 * The command palette (`⌘K`): find a run by id, PR number or workflow, start a new run, review a
 * waiting gate, toggle the theme, or go to any section. Runs come from `GET /runs?q=`; the
 * commands are filtered here.
 */
export function CommandPalette({
  open,
  onOpenChange,
  baseUrl = apiBaseUrl(),
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  baseUrl?: string;
}) {
  const router = useRouter();
  const { resolvedTheme, setTheme } = useTheme();
  const workspaceId = useWorkspaceId();
  const [search, setSearch] = useState("");
  const query = useDebounced(search.trim(), DEBOUNCE_MS);
  const runs = useRunSearch(query, { workspaceId, baseUrl });
  const waitingRuns = useWaitingRuns({ workspaceId, baseUrl });
  // Leaves out a gate past its time to live, even before its run is cancelled. Read only in the
  // browser: the shell prerenders, where the clock may not be read.
  const now = useClientNow(30_000);

  const close = (next = false) => {
    onOpenChange(next);
    if (!next) setSearch("");
  };
  const go = (href: string) => {
    close();
    router.push(href);
  };

  const found = query === "" ? [] : (runs.data ?? []);
  const searching = query !== "" && runs.isFetching && runs.data === undefined;
  // A full id the search did not find (another workspace's run) still opens its console.
  const fullId = FULL_ID.test(query) && !found.some((r) => r.id === query.toLowerCase());
  const loadedWaiting = waitingRuns.data?.pages[0]?.items ?? [];
  const toReview =
    now === null
      ? []
      : query === ""
        ? inboxRuns(loadedWaiting, now).slice(0, 1)
        : inboxRuns(found, now);

  const actions: PaletteCommand[] = [
    { id: "new-run", label: "New run", icon: PlusIcon, href: "/runs?new=1" },
    {
      id: "theme",
      label: resolvedTheme === "dark" ? "Switch to light theme" : "Switch to dark theme",
      icon: MoonIcon,
      run: () => {
        setTheme(resolvedTheme === "dark" ? "light" : "dark");
        close();
      },
    },
  ].filter((c) => matches(c.label, query));
  const pages: PaletteCommand[] = [
    ...NAV_ITEMS.map((item) => ({
      id: item.href,
      label: item.label,
      icon: item.icon,
      href: item.href,
    })),
    ...SETTINGS_PAGES.map((page) => ({
      id: page.href,
      label: `Settings: ${page.label}`,
      icon: page.icon,
      href: page.href,
    })),
  ].filter((c) => matches(c.label, query));

  return (
    <CommandDialog
      open={open}
      onOpenChange={close}
      title="Command palette"
      description="Find a run by id, pull request or workflow, or run a command."
      className="sm:max-w-xl"
    >
      {/* Runs are matched by the API, commands below; cmdk's own filter would hide both. */}
      <Command shouldFilter={false}>
        <CommandInput
          value={search}
          onValueChange={setSearch}
          placeholder="Run id, PR number, workflow or command…"
        />
        <CommandList className="max-h-96">
          <CommandEmpty>
            {searching ? "Searching…" : `Nothing matches “${search.trim()}”.`}
          </CommandEmpty>
          {query !== "" && (found.length > 0 || searching || runs.isError || fullId) ? (
            <CommandGroup heading="Runs">
              {searching ? (
                <CommandItem disabled value="searching">
                  <LoaderCircleIcon aria-hidden="true" className="animate-spin" />
                  Searching runs…
                </CommandItem>
              ) : null}
              {runs.isError ? (
                <CommandItem value="retry" onSelect={() => void runs.refetch()}>
                  <AlertCircleIcon aria-hidden="true" className="text-destructive" />
                  Could not search runs. Retry
                </CommandItem>
              ) : null}
              {found.map((run) => (
                <CommandItem
                  key={run.id}
                  value={`run-${run.id}`}
                  onSelect={() => go(`/runs/${run.id}`)}
                >
                  <RunRow run={run} />
                </CommandItem>
              ))}
              {fullId ? (
                <CommandItem value="open-id" onSelect={() => go(`/runs/${query.toLowerCase()}`)}>
                  <ExternalLinkIcon aria-hidden="true" />
                  Open run <span className="font-mono">{shortId(query.toLowerCase())}</span>
                </CommandItem>
              ) : null}
            </CommandGroup>
          ) : null}
          {toReview.length > 0 || actions.length > 0 ? (
            <CommandGroup heading="Actions">
              {toReview.map((run) => (
                <CommandItem
                  key={run.id}
                  value={`approve-${run.id}`}
                  onSelect={() => go(`/inbox?run=${run.id}`)}
                >
                  <CheckCircleIcon aria-hidden="true" />
                  <span className="min-w-0 truncate">
                    Approve: {run.waiting_gate?.title ?? run.workflow.name}
                  </span>
                  <span className="font-mono text-meta text-muted-foreground">
                    {shortId(run.id)}
                  </span>
                </CommandItem>
              ))}
              {actions.map((c) => (
                <CommandItem
                  key={c.id}
                  value={c.id}
                  onSelect={() => (c.href ? go(c.href) : c.run?.())}
                >
                  <c.icon aria-hidden="true" />
                  {c.label}
                </CommandItem>
              ))}
            </CommandGroup>
          ) : null}
          {pages.length > 0 ? (
            <CommandGroup heading="Go to">
              {pages.map((c) => (
                <CommandItem key={c.id} value={c.id} onSelect={() => go(c.href ?? "/")}>
                  <c.icon aria-hidden="true" />
                  {c.label}
                </CommandItem>
              ))}
            </CommandGroup>
          ) : null}
        </CommandList>
      </Command>
    </CommandDialog>
  );
}
