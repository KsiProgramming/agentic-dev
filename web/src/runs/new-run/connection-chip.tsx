"use client";

import { CircleAlertIcon, CircleCheckIcon, CircleDashedIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import type { ConnectionState } from "./readiness";

/** Whether one connection is there, as icon + label: on template cards ("Requires", the label is
 * the connection's name) and in the new workflow's provider picker (5.8, no label: the state is
 * the label). */
export function ConnectionChip({ label, state }: { label?: string; state: ConnectionState }) {
  const ok = state === "ready";
  const Icon = ok ? CircleCheckIcon : state === "attention" ? CircleAlertIcon : CircleDashedIcon;
  const text = ok ? "connected" : state === "loading" ? "checking" : "not connected";
  return (
    <Badge
      variant="outline"
      data-state={state}
      className={cn(ok ? "text-status-succeeded" : "text-muted-foreground")}
    >
      <Icon aria-hidden="true" data-icon="inline-start" />
      {label ? (
        <>
          <span className="text-foreground">{label}</span>
          <span className="sr-only">: {text}</span>
        </>
      ) : (
        <span>{text.charAt(0).toUpperCase() + text.slice(1)}</span>
      )}
    </Badge>
  );
}
