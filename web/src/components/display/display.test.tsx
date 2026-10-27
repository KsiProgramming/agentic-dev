import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { TokenUsage } from "@/runs/cost";

import {
  Duration,
  ExpiresIn,
  IdChip,
  Money,
  RelativeTime,
  StatTile,
  TokenCount,
  WaitingTime,
} from ".";

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("sonner", () => ({ toast }));

const NOW = Date.parse("2026-10-22T12:00:00Z");
const RUN_ID = "1a2b3c4d-0000-4000-8000-000000000000";

function usage(overrides: Partial<TokenUsage> = {}): TokenUsage {
  return {
    inputTokens: 12_300,
    outputTokens: 2_100,
    cacheReadTokens: 0,
    cacheWriteTokens: 0,
    estimatedUsd: 0.042,
    costComplete: true,
    unpricedModels: [],
    ...overrides,
  };
}

/** Hovering or focusing a value opens its tooltip; Radix renders the text twice (visible and for
 * screen readers), so this reads the visible copy. */
async function tooltipOf(element: HTMLElement): Promise<string> {
  fireEvent.focus(element);
  fireEvent.pointerMove(element);
  const tip = await screen.findByRole("tooltip");
  return tip.textContent ?? "";
}

afterEach(() => vi.unstubAllGlobals());

describe("RelativeTime", () => {
  it("says how long ago in a <time> and gives the exact time in its tooltip", async () => {
    render(<RelativeTime iso="2026-10-22T11:55:00Z" now={NOW} prefix="Started " />);

    const time = screen.getByText("Started 5 min ago");
    expect(time.tagName).toBe("TIME");
    expect(time.getAttribute("datetime")).toBe("2026-10-22T11:55:00Z");
    expect(time.className).toContain("tabular-nums");
    expect(time.tabIndex).toBe(0);
    expect(await tooltipOf(time)).toContain("Oct 22, 2026, 11:55:00 AM");
  });

  it("shows the time of day for a log line, and takes no focus in a list", () => {
    render(<RelativeTime iso="2026-10-22T11:55:07Z" clock focusable={false} />);

    const time = screen.getByText("11:55:07 AM");
    expect(time.hasAttribute("tabindex")).toBe(false);
  });

  it("adds a detail line to its tooltip", async () => {
    render(<RelativeTime iso="2026-10-22T11:55:00Z" now={NOW} detail="1h 02m start to end" />);

    const tip = await tooltipOf(screen.getByText("5 min ago"));
    expect(tip).toContain("Oct 22, 2026, 11:55:00 AM");
    expect(tip).toContain("1h 02m start to end");
  });
});

describe("Duration", () => {
  it("formats milliseconds, and says — before anything started", () => {
    render(
      <>
        <Duration ms={125_000} data-testid="took" />
        <Duration ms={null} data-testid="none" />
      </>,
    );

    expect(screen.getByTestId("took").textContent).toBe("2m 05s");
    expect(screen.getByTestId("took").className).toContain("tabular-nums");
    expect(screen.getByTestId("none").textContent).toBe("—");
  });
});

describe("ExpiresIn", () => {
  it("counts down to the moment, then says Expired, with the moment in a time element", () => {
    render(
      <>
        <ExpiresIn iso="2026-10-24T12:00:00Z" now={NOW} />
        <ExpiresIn iso="2026-10-22T12:05:00Z" now={NOW} />
        <ExpiresIn iso="2026-10-22T11:00:00Z" now={NOW} focusable={false} />
      </>,
    );

    const times = [...document.querySelectorAll("time")];
    expect(times.map((t) => t.textContent)).toEqual([
      "Expires in 2 d",
      "Expires in 5 min",
      "Expired",
    ]);
    expect(times[0]!.getAttribute("dateTime")).toBe("2026-10-24T12:00:00Z");
    expect(times[0]!.tabIndex).toBe(0);
    expect(times[2]!.hasAttribute("tabindex")).toBe(false);
  });
});

describe("WaitingTime", () => {
  it("says waiting while live, waited after, and nothing when the run never waited", () => {
    render(
      <>
        <WaitingTime ms={725_000} live data-testid="live" />
        <WaitingTime ms={3_600_000} data-testid="after" />
        <WaitingTime ms={0} data-testid="never" />
      </>,
    );

    expect(screen.getByTestId("live").textContent).toBe("waiting 12m 05s");
    expect(screen.getByTestId("after").textContent).toBe("waited 1h 00m");
    expect(screen.queryByTestId("never")).toBeNull();
  });
});

describe("Money", () => {
  it("shows a cost with every token count in its tooltip, and the budget", async () => {
    render(<Money usage={usage()} budget={5} data-testid="cost" />);

    const cost = screen.getByTestId("cost");
    expect(cost.textContent).toBe("$0.042 of $5.00");
    const tip = await tooltipOf(cost);
    expect(tip).toContain("12,300 input · 2,100 output");
    expect(tip).toContain("$5.00 budget");
  });

  it("says why a cost is missing, on screen readers too", async () => {
    render(
      <Money
        usage={usage({ estimatedUsd: 0, costComplete: false, unpricedModels: ["mystery"] })}
        data-testid="cost"
      />,
    );

    const cost = screen.getByTestId("cost");
    expect(cost.textContent).toMatch(/^— \(No price for mystery/);
    expect(await tooltipOf(cost)).toContain("No price for mystery");
  });

  it("shows a plain amount as a cost or as a price", () => {
    render(
      <>
        <Money usd={0.0423} data-testid="cost" />
        <Money usd={3} kind="price" data-testid="price" />
      </>,
    );

    expect(screen.getByTestId("cost").textContent).toBe("$0.0423");
    expect(screen.getByTestId("price").textContent).toBe("$3.00");
  });
});

describe("TokenCount", () => {
  it("is short on screen and exact in its tooltip", async () => {
    render(<TokenCount value={12_345} label="tokens" data-testid="tokens" />);

    const tokens = screen.getByTestId("tokens");
    expect(tokens.textContent).toBe("12.3K tokens");
    expect(await tooltipOf(tokens)).toContain("12,345 tokens");
  });
});

describe("IdChip", () => {
  it("shows the short id and copies the full one", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    render(<IdChip id={RUN_ID} label="run id" />);

    const chip = screen.getByRole("button", { name: "Copy run id 1a2b3c4d" });
    expect(chip.textContent).toBe("1a2b3c4d");
    expect(chip.className).toContain("font-mono");
    expect(await tooltipOf(chip)).toContain(RUN_ID);

    fireEvent.click(chip);
    expect(writeText).toHaveBeenCalledWith(RUN_ID);
    await vi.waitFor(() => expect(toast.success).toHaveBeenCalledWith("Run id copied"));
  });

  it("links to what it names", () => {
    render(<IdChip id={RUN_ID} label="run" href={`/runs/${RUN_ID}`} />);

    const link = screen.getByRole("link", { name: "Run 1a2b3c4d" });
    expect(link.getAttribute("href")).toBe(`/runs/${RUN_ID}`);
    expect(link.textContent).toBe("1a2b3c4d");
  });
});

describe("StatTile", () => {
  it("pairs a label with its value and one line of context", () => {
    render(<StatTile label="Cost" value="$0.42" secondary="of $5.00 budget" />);

    const term = screen.getByRole("term");
    expect(term.textContent).toBe("Cost");
    const [value, secondary] = screen.getAllByRole("definition");
    expect(value.textContent).toBe("$0.42");
    expect(value.className).toContain("text-stat");
    expect(secondary.textContent).toBe("of $5.00 budget");
  });
});
