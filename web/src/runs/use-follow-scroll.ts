"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

/** How close to the bottom (px) still counts as "at the bottom". */
const SLACK = 48;

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
 * content is added. Once the user scrolls up, following stops and `behind` turns true when new
 * content arrives; `jump()` scrolls to the bottom and follows again.
 */
export function useFollowScroll(version: number, active: boolean) {
  const [following, setFollowing] = useState(true);
  const [behind, setBehind] = useState(false);
  const followingRef = useRef(following);

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

  useLayoutEffect(() => {
    if (!active || version === 0) return;
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
