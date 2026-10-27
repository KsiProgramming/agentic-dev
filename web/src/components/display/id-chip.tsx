"use client";

import { CopyIcon } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";

import { cn } from "@/lib/utils";

import { shortId } from "./short-id";
import { ValueTooltip } from "./value-tooltip";

const CHIP =
  "inline-flex w-fit items-center gap-1 rounded-sm font-mono tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-ring/50";

/**
 * An id in short (mono, 8 characters) with the full id in a tooltip. With `href` it links to what
 * it names ("Run 1a2b3c4d" with `label="run"`); otherwise a click copies the full id ("Copy run id
 * 1a2b3c4d" with `label="run id"`). In a list row, `focusable={false}` shows it as plain text, the
 * full id still in its tooltip on hover, so it adds no tab stop.
 */
export function IdChip({
  id,
  label = "id",
  href,
  focusable = true,
  className,
}: {
  id: string;
  label?: string;
  href?: string;
  focusable?: boolean;
  className?: string;
}) {
  const short = shortId(id);
  const name = label.charAt(0).toUpperCase() + label.slice(1);
  if (href) {
    return (
      <ValueTooltip content={id}>
        <Link
          href={href}
          aria-label={`${name} ${short}`}
          className={cn(CHIP, "text-primary hover:underline", className)}
        >
          {short}
        </Link>
      </ValueTooltip>
    );
  }
  if (!focusable) {
    return (
      <ValueTooltip content={id}>
        <span className={cn(CHIP, className)}>{short}</span>
      </ValueTooltip>
    );
  }
  return (
    <ValueTooltip content={id}>
      <button
        type="button"
        aria-label={`Copy ${label} ${short}`}
        onClick={() => {
          void navigator.clipboard?.writeText(id).then(
            () => toast.success(`${name} copied`),
            () => toast.error(`Could not copy the ${label}`),
          );
        }}
        className={cn(
          CHIP,
          "px-1 text-muted-foreground hover:bg-muted hover:text-foreground",
          className,
        )}
      >
        {short}
        <CopyIcon aria-hidden="true" className="size-3.5" />
      </button>
    </ValueTooltip>
  );
}
