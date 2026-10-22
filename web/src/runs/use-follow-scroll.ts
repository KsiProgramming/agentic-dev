"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

/** How close to the bottom (px) still counts as "at the bottom". */
const SLACK = 48;

/** Opening a run replays its stored events in a burst; content added this soon after the page
 * goes live is that replay, not news, so it neither scrolls the page nor shows the pill. */
const REPLAY_MS = 1500;

function atBottom(): boolean {
  return window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - SLACK;
}

function scrollToBottom(smooth: boolean) {
  const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  window.scrollTo({
    top: document.documentElement.scrollHeight,
    behavior: smooth && !reduce ? "smooth" : "auto",
  });
}

/**
 * Follow new content while the user is at the bottom of the page. `version` changes whenever
 * content is added. The page opens where it is (the top) and starts following once the user
 * scrolls to the bottom. While not following, `behind` turns true when new content arrives;
 * `jump()` scrolls to the bottom and follows again.
 */
export function useFollowScroll(version: number, active: boolean) {
  const [following, setFollowing] = useState(false);
  const [behind, setBehind] = useState(false);
  const followingRef = useRef(false);
  const liveSince = useRef<number | null>(null);

  useEffect(() => {
    const onScroll = () => {
      const bottom = atBottom();
      if (bottom !== followingRef.current) {
        followingRef.current = bottom;
        setFollowing(bottom);
      }
      if (bottom) setBehind(false);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    liveSince.current = active ? Date.now() : null;
  }, [active]);

  useLayoutEffect(() => {
    if (!active || version === 0) return;
    if (liveSince.current === null || Date.now() - liveSince.current < REPLAY_MS) return;
    if (followingRef.current) scrollToBottom(false);
    else setBehind(true);
  }, [version, active]);

  const jump = useCallback(() => {
    followingRef.current = true;
    setFollowing(true);
    setBehind(false);
    scrollToBottom(true);
  }, []);

  return { following, behind: active && behind, jump };
}
