import { ExternalLinkIcon } from "lucide-react";

import { IdChip } from "@/components/display";

import { RerunOf } from "./rerun";

interface Triggered {
  trigger: string;
  rerun_of?: string | null;
  rerun_from?: { node_id: string } | null;
  jira_issue?: { site: string; key: string; url: string } | null;
  pr_review?: { number: number; comment_url: string } | null;
}

/** What started a run, as words: "Manual", "API", "Rerun", "Jira" (7.3), "GitHub" (7.6). */
export function triggerText(run: Triggered): string {
  if (run.trigger === "manual") return "Manual";
  if (run.trigger === "api") return "API";
  if (run.trigger === "jira") return run.jira_issue ? `Jira · ${run.jira_issue.key}` : "Jira";
  if (run.trigger === "github") {
    return run.pr_review ? `GitHub · PR #${run.pr_review.number} review` : "GitHub";
  }
  return "Rerun";
}

const LINK =
  "relative z-10 inline-flex items-center gap-1 text-foreground-secondary hover:text-foreground hover:underline";

/** What started the run: "Manual", "API", "Rerun of <id>" (a link to it), "Jira · PROJ-12"
 * (the key links to the issue in Jira) or, for a follow-up of a pull request review (7.6),
 * "GitHub · PR #42 review" (linking to the comment that asked) and "Follow-up of <id>". The
 * links sit above a row's stretched link. */
export function RunTrigger({ run }: { run: Triggered }) {
  if (run.trigger === "github") return <ReviewTrigger run={run} />;
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

function ReviewTrigger({ run }: { run: Triggered }) {
  const review = run.pr_review;
  // The link is the comment's page on github.com, as the API stored it; nothing else is linked.
  const url = review?.comment_url ?? "";
  const safe = url.startsWith("https://github.com/");
  const label = review ? `PR #${review.number} review` : null;
  return (
    <span className="inline-flex flex-wrap items-center gap-x-1">
      <span>
        GitHub
        {label ? (
          <>
            {" · "}
            {safe ? (
              <a href={url} target="_blank" rel="noreferrer" className={LINK}>
                {label}
                <ExternalLinkIcon aria-hidden="true" className="size-3" />
                <span className="sr-only">(opens the comment on GitHub in a new tab)</span>
              </a>
            ) : (
              <span>{label}</span>
            )}
          </>
        ) : null}
      </span>
      {run.rerun_of ? (
        <span>
          {" · "}Follow-up of{" "}
          <IdChip
            id={run.rerun_of}
            label="run"
            href={`/runs/${run.rerun_of}`}
            className="relative z-10"
          />
        </span>
      ) : null}
    </span>
  );
}
