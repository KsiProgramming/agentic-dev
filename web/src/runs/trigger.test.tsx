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
