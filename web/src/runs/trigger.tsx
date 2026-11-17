import { ExternalLinkIcon } from "lucide-react";

import { RerunOf } from "./rerun";

interface Triggered {
  trigger: string;
  rerun_of?: string | null;
  rerun_from?: { node_id: string } | null;
  jira_issue?: { site: string; key: string; url: string } | null;
}

/** What started a run, as words: "Manual", "API", "Rerun", "Jira" (7.3). */
export function triggerText(run: Triggered): string {
  if (run.trigger === "manual") return "Manual";
  if (run.trigger === "api") return "API";
  if (run.trigger === "jira") return run.jira_issue ? `Jira · ${run.jira_issue.key}` : "Jira";
  return "Rerun";
}

/** What started the run: "Manual", "API", "Rerun of <id>" (a link to it) or "Jira · PROJ-12"
 * (the key links to the issue in Jira). The link sits above a row's stretched link. */
export function RunTrigger({ run }: { run: Triggered }) {
  if (run.rerun_of) {
    return <RerunOf runId={run.rerun_of} fromStep={run.rerun_from?.node_id} />;
  }
  const issue = run.jira_issue;
  if (run.trigger === "jira" && issue) {
    // The URL is built by the API from the site it stored, never taken from a delivery.
    const safe = issue.url.startsWith("https://");
    return (
      <span>
        Jira ·{" "}
        {safe ? (
          <a
            href={issue.url}
            target="_blank"
            rel="noreferrer"
            className="relative z-10 inline-flex items-center gap-1 font-mono text-foreground-secondary hover:text-foreground hover:underline"
          >
            {issue.key}
            <ExternalLinkIcon aria-hidden="true" className="size-3" />
            <span className="sr-only">(opens Jira in a new tab)</span>
          </a>
        ) : (
          <span className="font-mono">{issue.key}</span>
        )}
      </span>
    );
  }
  return <span>{triggerText(run)}</span>;
}
