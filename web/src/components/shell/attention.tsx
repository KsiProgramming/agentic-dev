"use client";

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { apiBaseUrl } from "@/api/client";
import { inboxRuns, useWaitingRuns, WAITING_LIMIT } from "@/inbox/waiting";
import { useRunsStream } from "@/runs/use-runs-stream";
import { useWorkspaceId } from "@/workspace";

/** What needs the user, shared by the shell (sidebar badge, page title) and the run console. */
interface Attention {
  /** Runs of the workspace waiting at a gate (capped at `WAITING_LIMIT`). */
  waiting: number;
  /** The run console shows a run waiting at a gate. */
  setConsoleWaiting: (waiting: boolean) => void;
}

const AttentionContext = createContext<Attention>({ waiting: 0, setConsoleWaiting: () => {} });

/** The count as shown: "99+" past the limit. */
export function countLabel(count: number): string {
  return count >= WAITING_LIMIT ? `${WAITING_LIMIT - 1}+` : String(count);
}

const TITLE_PREFIX = /^(?:\(\d+\+?\) )?● Needs approval · /;

/** The page title with what needs the user in front: "● Needs approval · " on the console of a
 * waiting run, "(N) ● Needs approval · " on every other page while N runs wait. Next.js sets
 * the title on each navigation, so it is put back whenever the `<title>` changes. */
export function attentionTitle(title: string, waiting: number, consoleWaiting: boolean): string {
  const base = title.replace(TITLE_PREFIX, "");
  if (consoleWaiting) return `● Needs approval · ${base}`;
  if (waiting > 0) return `(${countLabel(waiting)}) ● Needs approval · ${base}`;
  return base;
}

function useAttentionTitle(waiting: number, consoleWaiting: boolean) {
  useEffect(() => {
    const apply = () => {
      const next = attentionTitle(document.title, waiting, consoleWaiting);
      if (document.title !== next) document.title = next;
    };
    apply();
    const observer = new MutationObserver(apply);
    observer.observe(document.head, { subtree: true, childList: true, characterData: true });
    return () => {
      observer.disconnect();
      document.title = document.title.replace(TITLE_PREFIX, "");
    };
  }, [waiting, consoleWaiting]);
}

/** Keeps the workspace's waiting runs counted, live from `GET /runs/stream`, and the page title
 * in step with them. */
export function AttentionProvider({
  children,
  baseUrl = apiBaseUrl(),
  workspaceId: givenWorkspaceId,
}: {
  children: ReactNode;
  baseUrl?: string;
  workspaceId?: string;
}) {
  const workspaceId = useWorkspaceId(givenWorkspaceId);
  // Kept live by the runs stream below, like the runs page's lists; the Inbox lists the same.
  const waitingRuns = useWaitingRuns({ workspaceId, baseUrl });
  useRunsStream({ workspaceId, baseUrl });
  // A gate past its time to live no longer waits, even before the worker has cancelled its run.
  const now = useClientNow(30_000);
  const loaded = waitingRuns.data?.pages[0]?.items ?? [];
  const waiting = now === null ? loaded.length : inboxRuns(loaded, now).length;
  const [consoleWaiting, setConsoleWaiting] = useState(false);
  useAttentionTitle(waiting, consoleWaiting);
  const value = useMemo(() => ({ waiting, setConsoleWaiting }), [waiting]);
  return <AttentionContext.Provider value={value}>{children}</AttentionContext.Provider>;
}

/** The time every `intervalMs`, read only in the browser: `null` while the shell prerenders,
 * which may not read the clock. */
export function useClientNow(intervalMs: number): number | null {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    const first = setTimeout(tick, 0);
    const id = setInterval(tick, intervalMs);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [intervalMs]);
  return now;
}

/** How many runs of the workspace wait at a gate. */
export function useWaitingCount(): number {
  return useContext(AttentionContext).waiting;
}

/** Tells the shell the console shows a run waiting at a gate, for the page title. */
export function useConsoleWaiting(waiting: boolean) {
  const { setConsoleWaiting } = useContext(AttentionContext);
  useEffect(() => {
    setConsoleWaiting(waiting);
    return () => setConsoleWaiting(false);
  }, [waiting, setConsoleWaiting]);
}
