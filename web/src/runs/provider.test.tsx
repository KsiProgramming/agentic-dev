import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import { Money } from "@/components/display";
import { renderWithQueries } from "@/testing/api";

import { ProviderFallbackNote } from "./console/provider-fallback-note";
import { StepUsage } from "./console/step-usage";
import { StepList } from "./console/step-list";
import { stepEntries } from "./console/step-entries";
import { usageOfEvent } from "./cost";
import { RunsList } from "./runs-list";
import { runEvent, runSummary } from "./testing";
import { buildTimeline, stepUsage } from "./timeline";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

const COPILOT_USAGE = {
  model: "gpt-5",
  input_tokens: 1000,
  output_tokens: 200,
  cache_read_tokens: 0,
  cache_write_tokens: 0,
  ai_credits: 1.26,
  estimated_usd: 0.0126,
};

function events(started: Record<string, unknown>, usage: Record<string, unknown>) {
  return [
    runEvent(1, "run_started", { workflow_name: "W" }),
    { ...runEvent(2, "node_started", started), node_id: "reviewer" },
    { ...runEvent(3, "usage", usage), node_id: "reviewer" },
    { ...runEvent(4, "node_completed"), node_id: "reviewer" },
  ];
}

test("a step records the provider and model from its start, and the model its usage reports", () => {
  const timeline = buildTimeline(events({ provider: "copilot", model: null }, COPILOT_USAGE));

  const [step] = timeline.steps;
  expect(step!.provider).toBe("copilot");
  expect(step!.model).toBe("gpt-5"); // a Copilot node starts with no model: the call says
  const claude = buildTimeline(
    events(
      { provider: "claude", model: "claude-opus-5-5" },
      { ...COPILOT_USAGE, model: null, ai_credits: null },
    ),
  );
  expect(claude.steps[0]!.model).toBe("claude-opus-5-5");
  // A run from before 8.3 has neither.
  const old = buildTimeline(events({}, { ...COPILOT_USAGE, model: null }));
  expect([old.steps[0]!.provider, old.steps[0]!.model]).toEqual([null, null]);
});

test("AI credits add up with the tokens and are kept apart from Claude's usage", () => {
  const timeline = buildTimeline([
    ...events({ provider: "copilot", model: null }, COPILOT_USAGE),
    { ...runEvent(5, "usage", COPILOT_USAGE), node_id: "reviewer" },
  ]);

  const usage = stepUsage(timeline.steps[0]!)!;
  expect(usage.aiCredits).toBeCloseTo(2.52);
  expect(usage.estimatedUsd).toBeCloseTo(0.0252);
  expect(usageOfEvent({ input_tokens: 1, output_tokens: 1 }).aiCredits).toBe(0);
});

test("the step list names the provider and model that ran each agent, in the mono font", () => {
  const timeline = buildTimeline(events({ provider: "copilot", model: null }, COPILOT_USAGE));
  const entries = stepEntries(timeline.steps);

  render(
    <TooltipProvider>
      <StepList
        entries={entries}
        selected={null}
        now={Date.now()}
        kindOf={() => null}
        onSelect={() => {}}
      />
    </TooltipProvider>,
  );

  const label = screen.getByTestId("step-provider");
  expect(label.dataset.provider).toBe("copilot");
  expect(label.textContent).toBe("Copilot·gpt-5");
  expect(screen.getByTestId("step-model").className).toContain("font-mono");
});

test("a Copilot step's Usage tab shows its AI credits beside the tokens, and a priced cost", async () => {
  const timeline = buildTimeline(events({ provider: "copilot", model: null }, COPILOT_USAGE));
  const [step] = timeline.steps;

  render(
    <TooltipProvider>
      <StepUsage step={step!} items={[]} />
    </TooltipProvider>,
  );

  expect(screen.getByText("Ran on").parentElement!.textContent).toContain("Copilot");
  expect(screen.getByTestId("step-credits").textContent).toBe("1.26");
  const cost = screen.getByTestId("step-cost");
  expect(cost.textContent).toBe("$0.0126");
  fireEvent.focus(cost);
  const tips = await screen.findAllByText(/list price of the credits/);
  expect(tips[0]!.textContent).toContain("not what the person's plan charged");
});

test("a Claude step shows no AI credits tile", () => {
  const timeline = buildTimeline(
    events(
      { provider: "claude", model: "claude-opus-5-5" },
      { ...COPILOT_USAGE, ai_credits: null, model: "claude-opus-5-5" },
    ),
  );

  render(
    <TooltipProvider>
      <StepUsage step={timeline.steps[0]!} items={[]} />
    </TooltipProvider>,
  );

  expect(screen.queryByTestId("step-credits")).toBeNull();
  expect(screen.getByTestId("step-provider").dataset.provider).toBe("claude");
});

test("usage with no credits has no credits line in the cost tooltip", async () => {
  render(
    <TooltipProvider>
      <Money
        data-testid="cost"
        usage={{ ...usageOfEvent({ input_tokens: 5, output_tokens: 5, estimated_usd: 0.01 }) }}
      />
    </TooltipProvider>,
  );

  fireEvent.focus(screen.getByTestId("cost"));
  expect(await screen.findAllByText(/5 input/)).toBeTruthy();
  expect(screen.queryByText(/list price of the credits/)).toBeNull();
});

test("the fallback note says a trigger kept the run on Claude and names the agents", () => {
  render(<ProviderFallbackNote nodes={["builder", "reviewer"]} />);

  const note = screen.getByTestId("provider-fallback");
  expect(note.textContent).toContain("Ran on Claude");
  expect(note.textContent).toContain("triggers stay on Claude");
  expect(within(note).getByText("reviewer").className).toContain("font-mono");
});

test("provider_fallback in the events is what the timeline reports", () => {
  const timeline = buildTimeline([
    runEvent(1, "run_started", {}),
    runEvent(2, "provider_fallback", {
      nodes: ["a", "b"],
      reason: "triggered",
      provider: "claude",
    }),
  ]);

  expect(timeline.providerFallback).toEqual(["a", "b"]);
  expect(buildTimeline([runEvent(1, "run_started", {})]).providerFallback).toBeNull();
});

function list(runs: Parameters<typeof runSummary>[0][]) {
  return renderWithQueries(
    <RunsList
      runs={runs.map((r) => runSummary(r))}
      now={Date.now()}
      label="Runs"
      baseUrl="http://api.test"
    />,
  );
}

test("the runs list says nothing of a Claude run, names a Copilot run's login, and marks a mix", () => {
  list([
    { id: "r-claude" },
    { id: "r-copilot", provider: "copilot", providers: ["copilot"], copilot_login: "ada" },
    { id: "r-mixed", provider: "claude", providers: ["claude", "copilot"], copilot_login: "ada" },
  ]);

  const rows = within(screen.getByRole("table", { name: "Runs" })).getAllByRole("row");
  const fact = (id: string) =>
    within(rows.find((r) => r.dataset.runId === id)!).queryByTestId("copilot-login")?.textContent;
  expect(fact("r-claude")).toBeUndefined();
  expect(fact("r-copilot")).toBe("Copilot of ada");
  expect(fact("r-mixed")).toBe("Claude + Copilot of ada");
});
