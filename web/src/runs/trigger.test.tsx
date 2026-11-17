import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { RunTrigger, triggerText } from "./trigger";

const ISSUE = {
  site: "acme.atlassian.net",
  key: "API-12",
  url: "https://acme.atlassian.net/browse/API-12",
};

test("says what started a run", () => {
  expect(triggerText({ trigger: "manual" })).toBe("Manual");
  expect(triggerText({ trigger: "api" })).toBe("API");
  expect(triggerText({ trigger: "rerun" })).toBe("Rerun");
  expect(triggerText({ trigger: "jira", jira_issue: ISSUE })).toBe("Jira · API-12");
  expect(triggerText({ trigger: "jira" })).toBe("Jira");
  expect(triggerText({ trigger: "github", pr_review: REVIEW })).toBe("GitHub · PR #42 review");
  expect(triggerText({ trigger: "github" })).toBe("GitHub");
});

const REVIEW = {
  number: 42,
  comment_url: "https://github.com/acme/hello/pull/42#discussion_r7",
};
const ORIGINAL = "5a1d1f1e-0000-4000-8000-000000000001";

test("a follow-up links the review comment and the run it follows up", () => {
  render(<RunTrigger run={{ trigger: "github", pr_review: REVIEW, rerun_of: ORIGINAL }} />);
  const comment = screen.getByRole("link", { name: /PR #42 review/ });
  expect(comment.getAttribute("href")).toBe(REVIEW.comment_url);
  expect(comment.getAttribute("target")).toBe("_blank");
  expect(comment.getAttribute("rel")).toBe("noreferrer");
  expect(screen.getByText(/Follow-up of/)).toBeDefined();
  const original = screen.getAllByRole("link").find((a) => a !== comment);
  expect(original?.getAttribute("href")).toBe(`/runs/${ORIGINAL}`);
});

test("a review comment URL off github.com is shown as text, not a link", () => {
  render(
    <RunTrigger
      run={{ trigger: "github", pr_review: { ...REVIEW, comment_url: "https://evil.test/x" } }}
    />,
  );
  expect(screen.queryByRole("link")).toBeNull();
  expect(screen.getByText("PR #42 review")).toBeDefined();
});

test("a run started from Jira links its issue in a new tab", () => {
  render(<RunTrigger run={{ trigger: "jira", jira_issue: ISSUE }} />);
  const link = screen.getByRole("link", { name: /API-12/ });
  expect(link.getAttribute("href")).toBe(ISSUE.url);
  expect(link.getAttribute("target")).toBe("_blank");
  expect(link.getAttribute("rel")).toBe("noreferrer");
});

test("an issue URL that is not https is shown as text, not a link", () => {
  render(
    <RunTrigger run={{ trigger: "jira", jira_issue: { ...ISSUE, url: "javascript:alert(1)" } }} />,
  );
  expect(screen.queryByRole("link")).toBeNull();
  expect(screen.getByText("API-12")).toBeDefined();
});
