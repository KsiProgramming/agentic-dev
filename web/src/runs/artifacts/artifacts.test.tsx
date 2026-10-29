import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { pinDisplayLocale } from "@/lib/locale";

import { stepEntries, stepRows } from "../console/step-entries";
import { StepInput } from "../console/step-input";
import { StepOutput } from "../console/step-output";
import type { WorkflowSpec } from "../graph/spec-graph";
import { buildTimeline } from "../timeline";
import { runEvent } from "../testing";
import { ArtifactCards, ArtifactContent } from "./artifact-cards";
import {
  artifactKind,
  downloadUrl,
  formatSize,
  parseArtifacts,
  type ArtifactVersion,
} from "./artifacts";
import { ArtifactsView } from "./artifacts-view";

const BASE = "http://api.test";
const RUN = "run-1";
const FINDINGS: ArtifactVersion = {
  name: "findings.json",
  version: 2,
  nodeId: "scan",
  mediaType: "application/json",
  size: 1536,
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/** Answers the artifacts endpoints from `listed` and `contents` (by name). */
function api(listed: unknown[] | Response, contents: Record<string, string> = {}) {
  const fetch = vi.fn<(r: Request) => Promise<Response>>(async (request) => {
    const url = new URL(request.url);
    if (url.pathname === `/runs/${RUN}/artifacts`) {
      return listed instanceof Response ? listed : json(listed);
    }
    const one = /^\/runs\/[^/]+\/artifacts\/([^/]+)$/.exec(url.pathname);
    const name = one ? decodeURIComponent(one[1]!) : null;
    if (name !== null && name in contents) {
      return json({
        name,
        version: Number(url.searchParams.get("version")),
        versions: 2,
        node_id: "scan",
        media_type: "text/plain",
        size: 1,
        sha256: "x",
        created_at: "2026-10-28T10:00:00Z",
        content: contents[name],
      });
    }
    throw new Error(`unexpected ${request.method} ${request.url}`);
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

function withQueries(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

afterEach(() => {
  vi.unstubAllGlobals();
  pinDisplayLocale(null);
});

describe("artifacts", () => {
  test("payload entries without a name or version are left out", () => {
    expect(parseArtifacts([{ name: "a.md", version: 1 }, { name: "b.md" }, "x"])).toEqual([
      { name: "a.md", version: 1, nodeId: null, mediaType: null, size: null },
    ]);
    expect(parseArtifacts(undefined)).toEqual([]);
  });

  test("the kind comes from the media type, else the extension", () => {
    expect(artifactKind(FINDINGS)).toBe("JSON");
    expect(artifactKind({ name: "r.md", mediaType: null })).toBe("Markdown");
    expect(artifactKind({ name: "n.txt", mediaType: "text/plain" })).toBe("Text");
  });

  test("sizes and the download link", () => {
    pinDisplayLocale({ locale: "en-US", timeZone: "UTC" });
    expect(formatSize(512)).toBe("512 byte");
    expect(formatSize(1536)).toBe("1.5 kB");
    expect(formatSize(2 * 1024 * 1024)).toBe("2 MB");
    expect(downloadUrl(`${BASE}/`, RUN, "findings.json", 2)).toBe(
      `${BASE}/runs/run-1/artifacts/findings.json/download?version=2`,
    );
  });

  test("the timeline keeps what each step wrote and read", () => {
    const timeline = buildTimeline([
      runEvent(1, "node_started"),
      runEvent(2, "artifact_written", {
        name: "findings.json",
        version: 1,
        media_type: "application/json",
        size: 10,
        sha256: "x",
      }),
      runEvent(3, "node_completed"),
      {
        ...runEvent(4, "node_started", { reads: [{ name: "findings.json", version: 1 }] }),
        node_id: "report",
      },
    ]);

    const [scan, report] = timeline.steps;
    expect(scan?.artifactsWritten).toEqual([
      {
        name: "findings.json",
        version: 1,
        nodeId: "summarizer",
        mediaType: "application/json",
        size: 10,
      },
    ]);
    expect(report?.artifactsRead).toEqual([
      { name: "findings.json", version: 1, nodeId: null, mediaType: null, size: null },
    ]);
  });
});

describe("ArtifactContent", () => {
  test("JSON is shown in the JSON view", () => {
    render(<ArtifactContent artifact={FINDINGS} text='{"findings": [{"id": "F1"}]}' />);

    expect(screen.getByRole("group", { name: "findings.json" })).toBeTruthy();
    expect(screen.getByText('"F1"')).toBeTruthy();
  });

  test("Markdown drops raw HTML and images, and text stays text", () => {
    const markdown = { name: "report.md", version: 1, nodeId: null, mediaType: null, size: null };
    const { container } = render(
      <ArtifactContent
        artifact={markdown}
        text={"# Report\n\n<script>alert(1)</script>\n\n![x](https://evil.test/x.png)"}
      />,
    );
    expect(screen.getByRole("heading", { name: "Report" })).toBeTruthy();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();

    const notes = { name: "notes.txt", version: 1, nodeId: null, mediaType: null, size: null };
    render(<ArtifactContent artifact={notes} text="<b>not bold</b>" />);
    expect(screen.getByText("<b>not bold</b>")).toBeTruthy();
  });
});

describe("ArtifactCards", () => {
  test("a card opens the version's content in a sheet with Download", async () => {
    api([], { "findings.json": '{"findings": []}' });
    render(
      withQueries(
        <ArtifactCards
          runId={RUN}
          artifacts={[FINDINGS]}
          title="Artifacts written"
          baseUrl={BASE}
        />,
      ),
    );

    const section = screen.getByRole("region", { name: "Artifacts written" });
    fireEvent.click(within(section).getByTestId("artifact-card"));

    const sheet = await screen.findByTestId("artifact-sheet");
    expect(within(sheet).getByText(/written by scan/)).toBeTruthy();
    expect(await within(sheet).findByRole("group", { name: "findings.json" })).toBeTruthy();
    expect(within(sheet).getByRole("link", { name: "Download" }).getAttribute("href")).toBe(
      `${BASE}/runs/run-1/artifacts/findings.json/download?version=2`,
    );
  });
});

describe("ArtifactsView", () => {
  const LISTED = {
    name: "findings.json",
    version: 2,
    versions: 2,
    node_id: "scan",
    media_type: "application/json",
    size: 20,
    sha256: "x",
    created_at: "2026-10-28T10:00:00Z",
  };

  function view(onOpenStep = vi.fn(), live = false) {
    render(
      withQueries(
        <ArtifactsView
          runId={RUN}
          written={1}
          live={live}
          now={Date.parse("2026-10-28T10:05:00Z")}
          onOpenStep={onOpenStep}
          baseUrl={BASE}
        />,
      ),
    );
    return onOpenStep;
  }

  test("lists each artifact's latest version and opens its writer", async () => {
    api([LISTED]);
    const onOpenStep = view();

    const row = await screen.findByTestId("run-artifact");
    expect(within(row).getByText("findings.json")).toBeTruthy();
    expect(within(row).getByText(/v2 of 2/)).toBeTruthy();
    fireEvent.click(within(row).getByRole("button", { name: "scan" }));
    expect(onOpenStep).toHaveBeenCalledWith("scan");
  });

  test("says when there is none, live or not", async () => {
    api([]);
    view(vi.fn(), true);
    expect(await screen.findByText("No artifacts yet.")).toBeTruthy();
  });

  test("an error offers Retry", async () => {
    api(json({ detail: "boom" }, 500));
    view();
    expect(await screen.findByText(/Could not load the artifacts/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });
});

describe("the step panel", () => {
  test("a step's Output lists what it wrote, and its Input what it read", () => {
    const timeline = buildTimeline([
      runEvent(1, "node_started", { reads: [{ name: "plan.json", version: 3 }] }),
      runEvent(2, "message", { text: "Done." }),
      runEvent(3, "artifact_written", {
        name: "findings.json",
        version: 1,
        media_type: "application/json",
        size: 10,
      }),
      runEvent(4, "node_completed"),
    ]);
    const entries = stepEntries(timeline.steps);
    const [row] = stepRows(entries);
    if (!row) throw new Error("no row");

    render(
      withQueries(
        <StepOutput
          runId={RUN}
          step={row.step}
          row={row}
          kind="agent"
          entries={entries}
          onSelect={() => undefined}
        />,
      ),
    );
    const written = screen.getByRole("region", { name: "Artifacts written" });
    expect(within(written).getByText("findings.json")).toBeTruthy();
    expect(within(written).getByText(/JSON · .* · v1/)).toBeTruthy();

    const spec: WorkflowSpec = {
      spec_version: "0",
      id: "wf",
      name: "Workflow",
      root: {
        type: "agent",
        id: "summarizer",
        role: "Writer",
        instructions: "Go.",
        reads: ["plan.json"],
        writes: "findings.json",
      },
    };
    render(
      withQueries(<StepInput runId={RUN} row={row} spec={spec} runInput={null} first={false} />),
    );
    const read = screen.getByRole("region", { name: "Artifacts read" });
    expect(within(read).getByText("plan.json")).toBeTruthy();
    expect(within(read).getByText("JSON · v3")).toBeTruthy();
    expect(screen.getByText("Reads")).toBeTruthy();
    expect(screen.getByText("Writes")).toBeTruthy();
  });
});

describe("a merging reduce's output (4.5)", () => {
  const REPORT = {
    scanner: "merged",
    checks: [],
    findings: [
      {
        fingerprint: "f",
        tool: "ruff",
        rule: "F401",
        severity: "medium",
        category: "lint",
        path: "app.py",
        line: 1,
        message: "unused import",
        confidence: 0.5,
        sources: ["lint_repo", "lint_packages"],
      },
    ],
    counts: { medium: 1 },
    truncated: false,
    sources: [
      { id: "lint_repo", scanner: "lint", findings: 1 },
      { id: "lint_packages", scanner: "lint", findings: 1 },
    ],
  };

  function merged(written: boolean) {
    const events = [
      runEvent(1, "node_started"),
      ...(written
        ? [
            runEvent(2, "artifact_written", {
              name: "findings.json",
              version: 1,
              media_type: "application/json",
              size: 10,
              sha256: "x",
            }),
          ]
        : []),
      runEvent(3, "node_completed", { merged: { sources: 2, findings_in: 2, findings_out: 1 } }),
    ].map((e) => ({ ...e, node_id: "merge" }));
    const entries = stepEntries(buildTimeline(events).steps);
    const [row] = stepRows(entries);
    if (!row) throw new Error("no row");
    return withQueries(
      <StepOutput
        runId={RUN}
        baseUrl={BASE}
        step={row.step}
        row={row}
        kind="reduce"
        entries={entries}
        onSelect={() => undefined}
      />,
    );
  }

  test("shows the findings report it wrote", async () => {
    api([], { "findings.json": JSON.stringify(REPORT) });

    render(merged(true));

    expect(await screen.findByTestId("merged-from")).toBeTruthy();
    expect(screen.getAllByTestId("finding-sources")[0]!.textContent).toContain(
      "2 of 2 scans: lint_repo, lint_packages",
    );
  });

  test("without an artifact, says what it merged and how to see it", () => {
    render(merged(false));

    expect(
      screen.getByText(/Merged 2 findings into 1 from 2 sources\. Give the reduce/),
    ).toBeTruthy();
  });
});
