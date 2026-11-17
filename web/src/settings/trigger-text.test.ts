import { describe, expect, it } from "vitest";

import { fireBadge, ruleTarget, ruleWhen, webhookProblem } from "./trigger-text";

describe("trigger text", () => {
  it("says when a rule fires", () => {
    expect(ruleWhen({ on: "status", value: "In Progress" })).toBe("moves to In Progress");
    expect(ruleWhen({ on: "label", value: "agent" })).toBe("gets the label agent");
  });

  it("names what a rule runs", () => {
    const names = new Map([["jira-issue-answer", "Answer a Jira issue"]]);
    expect(ruleTarget({ template_id: "jira-issue-answer", workflow: null }, names)).toBe(
      "Answer a Jira issue",
    );
    expect(ruleTarget({ template_id: "gone", workflow: null }, names)).toBe("gone");
    expect(ruleTarget({ template_id: null, workflow: { id: "sdd", version: 3 } }, names)).toBe(
      "sdd · version 3",
    );
    expect(ruleTarget({ template_id: null, workflow: { id: "sdd" } }, names)).toBe("sdd");
  });

  it("shows each outcome as a status with its own words", () => {
    expect(fireBadge("started")).toEqual({ status: "succeeded", label: "Started a run" });
    expect(fireBadge("already_running")).toEqual({ status: "queued", label: "Run still going" });
    expect(fireBadge("start_failed")).toEqual({ status: "failed", label: "Not started" });
  });

  it("explains why Jira cannot reach a site", () => {
    expect(webhookProblem({ error: "url_conflict" })).toMatch(/another address/);
    expect(webhookProblem({ error: "something new" })).toBe("Jira cannot start runs on this site.");
  });
});
