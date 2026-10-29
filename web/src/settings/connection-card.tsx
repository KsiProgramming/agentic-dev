import {
  CircleAlertIcon,
  CircleCheckIcon,
  CircleDashedIcon,
  CircleMinusIcon,
  type LucideIcon,
} from "lucide-react";
import { useId, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export type ConnectionStatus = "connected" | "missing" | "attention" | "unavailable";

/** Icon + label, colour for status only (tech-stack → UI design system). */
const STATUS: Record<ConnectionStatus, { label: string; icon: LucideIcon; className: string }> = {
  connected: {
    label: "Connected",
    icon: CircleCheckIcon,
    className: "border-status-succeeded-border bg-status-succeeded-muted text-status-succeeded",
  },
  missing: {
    label: "Not connected",
    icon: CircleDashedIcon,
    className: "border-status-queued-border bg-status-queued-muted text-status-queued",
  },
  attention: {
    label: "Needs attention",
    icon: CircleAlertIcon,
    className: "border-status-waiting-border bg-status-waiting-muted text-status-waiting",
  },
  unavailable: {
    label: "Unavailable",
    icon: CircleMinusIcon,
    className: "border-status-queued-border bg-status-queued-muted text-status-queued",
  },
};

export function ConnectionBadge({ status }: { status: ConnectionStatus }) {
  const { label, icon: Icon, className } = STATUS[status];
  return (
    <Badge data-status={status} className={className}>
      <Icon aria-hidden="true" data-icon="inline-start" />
      {label}
    </Badge>
  );
}

/** One provider on the Settings page: what it is for, whether it is connected, and its actions
 * (on the right from `sm`, stacked below on mobile). `status` is unset while it loads. */
export function ConnectionCard({
  icon: Icon,
  title,
  purpose,
  status,
  detail,
  actions,
  children,
  testId,
}: {
  icon: LucideIcon;
  title: string;
  purpose: ReactNode;
  status?: ConnectionStatus;
  /** The account or key it is connected with, or why it is not. */
  detail?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  testId?: string;
}) {
  const headingId = useId();
  return (
    <Card role="region" aria-labelledby={headingId} data-testid={testId}>
      <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border bg-surface-subtle">
            <Icon aria-hidden="true" className="size-4 text-foreground-secondary" />
          </span>
          <div className="flex min-w-0 flex-col gap-1">
            <CardTitle className="flex flex-wrap items-center gap-2">
              <h2 id={headingId}>{title}</h2>
              {status ? <ConnectionBadge status={status} /> : null}
            </CardTitle>
            <CardDescription>{purpose}</CardDescription>
            {detail ? <div className="text-meta text-foreground-secondary">{detail}</div> : null}
          </div>
        </div>
        {actions ? <div className="flex flex-wrap gap-2 sm:shrink-0">{actions}</div> : null}
      </CardHeader>
      {children ? (
        <CardContent className="@container flex flex-col gap-3">{children}</CardContent>
      ) : null}
    </Card>
  );
}
