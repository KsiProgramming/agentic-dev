import type { JiraTrigger, JiraWebhook } from "@/api/queries";
import type { RunStatus } from "@/components/status-badge";

type Last = NonNullable<JiraTrigger["last"]>;

/** What a rule's last fire came to, as a status: colour is status only (CLAUDE.md rule 2). */
export function fireBadge(outcome: Last["outcome"]): { status: RunStatus; label: string } {
  switch (outcome) {
    case "started":
      return { status: "succeeded", label: "Started a run" };
    case "already_running":
      return { status: "queued", label: "Run still going" };
    case "start_failed":
      return { status: "failed", label: "Not started" };
  }
}

/** The "when" half of a rule, in words: `moves to In Progress`, `gets the label agent`. */
export function ruleWhen(rule: Pick<JiraTrigger, "on" | "value">): string {
  return rule.on === "status" ? `moves to ${rule.value}` : `gets the label ${rule.value}`;
}

/** What a rule runs: the template's name when known, else its id, or the stored workflow's id
 * (with its pinned version). */
export function ruleTarget(
  rule: Pick<JiraTrigger, "template_id" | "workflow">,
  templateNames: ReadonlyMap<string, string>,
): string {
  if (rule.template_id) return templateNames.get(rule.template_id) ?? rule.template_id;
  if (rule.workflow) {
    const version = rule.workflow.version;
    return version ? `${rule.workflow.id} · version ${version}` : rule.workflow.id;
  }
  return "a workflow";
}

/** Why Jira cannot reach a site's triggers (`error` of a failed webhook), for people. */
export const WEBHOOK_ERRORS: Record<string, string> = {
  url_conflict:
    "This Jira account already sends webhooks to another address. Remove them in Jira, or connect with another account.",
  limit: "This Jira account holds as many webhooks on the site as Jira allows (5).",
  needs_attention: "The Jira connection needs attention. Reconnect it in Integrations.",
  jira_unavailable: "Jira could not be reached. The next try is automatic.",
  refused: "Jira refused the webhook.",
  no_url: "The API does not know its public address. Set JIRA_WEBHOOK_BASE_URL.",
  not_connected: "Jira is not connected.",
};

export function webhookProblem(webhook: Pick<JiraWebhook, "error">): string {
  return WEBHOOK_ERRORS[webhook.error ?? ""] ?? "Jira cannot start runs on this site.";
}
