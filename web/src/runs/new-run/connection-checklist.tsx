"use client";

import {
  CircleAlertIcon,
  CircleCheckIcon,
  CircleDashedIcon,
  LoaderCircleIcon,
  type LucideIcon,
} from "lucide-react";
import { useId, useState } from "react";

import { useStartGithubInstall, type Requirement } from "@/api/queries";
import { ErrorState } from "@/components/states";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ClaudeKeyForm } from "@/settings/claude-key-form";

import { REQUIREMENT_LABEL, type ConnectionState, type Readiness } from "./readiness";

const ROW: Record<ConnectionState, { icon: LucideIcon; className: string; text: string }> = {
  loading: {
    icon: LoaderCircleIcon,
    className: "text-muted-foreground motion-safe:animate-spin",
    text: "Checking…",
  },
  ready: { icon: CircleCheckIcon, className: "text-status-succeeded", text: "Connected" },
  missing: { icon: CircleDashedIcon, className: "text-muted-foreground", text: "Not connected" },
  attention: {
    icon: CircleAlertIcon,
    className: "text-status-waiting",
    text: "Needs attention",
  },
  error: { icon: CircleAlertIcon, className: "text-destructive", text: "Could not check" },
};

const WHY: Record<Requirement, string> = {
  claude: "Agents run on Claude with your API key.",
  github: "The run works on a repository the GitHub App can reach, and opens a pull request.",
};

/** "Before you start": the connections a template needs, each with its fix in place. A Claude
 * key is entered right here; GitHub is installed on github.com, which comes back to
 * `returnTo`. */
export function ConnectionChecklist({
  requires,
  readiness,
  workspaceId,
  baseUrl,
  returnTo,
  navigate,
}: {
  requires: readonly Requirement[];
  readiness: Readiness;
  workspaceId: string;
  baseUrl?: string;
  returnTo: string;
  navigate?: (url: string) => void;
}) {
  const headingId = useId();
  const [addingKey, setAddingKey] = useState(false);
  const install = useStartGithubInstall({ workspaceId, baseUrl, navigate });

  if (readiness.error && requires.some((r) => readiness.state[r] === "error")) {
    return <ErrorState message={readiness.error} onRetry={readiness.retry} />;
  }

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2">
      <h3 id={headingId} className="text-meta font-medium">
        Before you start
      </h3>
      <ul
        className="flex flex-col divide-y divide-divider rounded-lg border"
        data-testid="connection-checklist"
      >
        {requires.map((requirement) => {
          const state = readiness.state[requirement];
          const { icon: Icon, className, text } = ROW[state];
          return (
            <li
              key={requirement}
              className="flex flex-col gap-3 p-3"
              data-requirement={requirement}
            >
              <div className="flex flex-wrap items-start gap-3">
                <Icon aria-hidden="true" className={`mt-0.5 size-4 shrink-0 ${className}`} />
                <div className="flex min-w-0 flex-1 flex-col">
                  <span className="font-medium">
                    {REQUIREMENT_LABEL[requirement]}
                    <span className="sr-only">: {text}</span>
                  </span>
                  <span className="text-meta text-foreground-secondary">
                    {state === "ready"
                      ? "Connected."
                      : state === "attention"
                        ? "The GitHub App was uninstalled or lost access."
                        : WHY[requirement]}
                  </span>
                </div>
                {requirement === "claude" && state === "missing" && !addingKey ? (
                  <Button type="button" size="sm" onClick={() => setAddingKey(true)}>
                    Add key
                  </Button>
                ) : null}
                {requirement === "github" && (state === "missing" || state === "attention") ? (
                  <Button
                    type="button"
                    size="sm"
                    onClick={() => install.mutate(returnTo)}
                    disabled={install.isPending}
                  >
                    {state === "attention" ? "Reconnect GitHub" : "Connect GitHub"}
                  </Button>
                ) : null}
              </div>
              {requirement === "claude" && state === "missing" && addingKey ? (
                <ClaudeKeyForm
                  workspaceId={workspaceId}
                  baseUrl={baseUrl}
                  onSaved={() => setAddingKey(false)}
                  onCancel={() => setAddingKey(false)}
                />
              ) : null}
            </li>
          );
        })}
      </ul>
      {install.error ? (
        <Alert variant="destructive">
          <AlertDescription>{install.error.message}</AlertDescription>
        </Alert>
      ) : null}
    </section>
  );
}
