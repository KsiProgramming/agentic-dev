"use client";

import { ExternalLinkIcon, ShieldCheckIcon } from "lucide-react";
import { useId, useState } from "react";

import { RelativeTime, TruncatedPath } from "@/components/display";
import { EmptyState } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import { formatCount } from "../cost";
import {
  checkLine,
  findingKey,
  location,
  SCANNER_LABEL,
  SEVERITIES,
  SEVERITY_DISPLAY,
  sortFindings,
  type Check,
  type Finding,
  type FindingsReport,
  type Severity,
  type Source,
} from "./findings";

/** Rows shown before "Show all". */
export const FINDINGS_SHOWN = 50;

/** Each severity's own hue (design-language.md → Severity colours), never a status's. Class
 * names are written out in full so Tailwind sees them. */
const SEVERITY_TONE: Record<Severity, string> = {
  critical: "border-severity-critical-border bg-severity-critical-muted text-severity-critical",
  high: "border-severity-high-border bg-severity-high-muted text-severity-high",
  medium: "border-severity-medium-border bg-severity-medium-muted text-severity-medium",
  low: "border-severity-low-border bg-severity-low-muted text-severity-low",
  info: "border-severity-info-border bg-severity-info-muted text-severity-info",
};

/** A severity as an icon and a word on its own colour; each severity's icon has its own shape,
 * so colour is never the only cue. */
export function SeverityBadge({ severity }: { severity: Severity }) {
  const { label, icon: Icon } = SEVERITY_DISPLAY[severity];
  return (
    <Badge data-severity={severity} className={SEVERITY_TONE[severity]}>
      <Icon aria-hidden="true" />
      {label}
    </Badge>
  );
}

/** The counts by severity on one line: those with findings as coloured badges, most severe
 * first, then the zeros as quiet text (design-language.md → Content rules, "Zeros are quiet"). */
function SeverityCounts({ counts }: { counts: FindingsReport["counts"] }) {
  const found = SEVERITIES.filter((s) => (counts[s] ?? 0) > 0);
  const zero = SEVERITIES.filter((s) => (counts[s] ?? 0) === 0);
  return (
    <p data-testid="severity-counts" className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
      {found.map((severity) => {
        const { label, icon: Icon } = SEVERITY_DISPLAY[severity];
        return (
          <Badge key={severity} data-severity={severity} className={SEVERITY_TONE[severity]}>
            <Icon aria-hidden="true" />
            {formatCount(counts[severity] ?? 0)} {label}
          </Badge>
        );
      })}
      {zero.length > 0 ? (
        <span className="text-caption text-placeholder">
          {zero.map((s) => `0 ${SEVERITY_DISPLAY[s].label}`).join(" · ")}
        </span>
      ) : null}
    </p>
  );
}

function Rule({ finding }: { finding: Finding }) {
  if (!finding.help_url) return <span className="font-mono whitespace-nowrap">{finding.rule}</span>;
  return (
    <a
      href={finding.help_url}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1 font-mono whitespace-nowrap text-foreground underline-offset-4 hover:underline"
    >
      {finding.rule}
      <ExternalLinkIcon aria-hidden="true" className="size-3.5 shrink-0" />
      <span className="sr-only">(opens the rule&apos;s page)</span>
    </a>
  );
}

/** The scanner's message, for a dependency what version fixes it, and in a merged report
 * which of its `sources` found it. Text, never HTML. */
export function Message({ finding, sources }: { finding: Finding; sources?: number }) {
  const fixed = finding.fixed_versions ?? [];
  return (
    <span className="flex min-w-0 flex-col gap-0.5">
      <span className="break-words">{finding.message}</span>
      {finding.category === "dependency" ? (
        <span className="text-caption text-foreground-secondary">
          {fixed.length > 0 ? `Fixed in ${fixed.join(", ")}` : "No fixed version yet"}
          {finding.aliases?.length ? ` · ${finding.aliases.join(", ")}` : ""}
        </span>
      ) : null}
      {finding.config === "platform-default" ? (
        <span className="text-caption text-muted-foreground">
          Platform default rules (the repo configures no linter here)
        </span>
      ) : null}
      {sources !== undefined && finding.sources?.length ? (
        <span data-testid="finding-sources" className="text-caption text-muted-foreground">
          {finding.sources.length} of {sources} scans:{" "}
          <span className="font-mono">{finding.sources.join(", ")}</span>
        </span>
      ) : null}
    </span>
  );
}

function FindingsTable({
  findings,
  label,
  sources,
}: {
  findings: Finding[];
  label: string;
  sources?: number;
}) {
  return (
    <Table aria-label={label}>
      <TableHeader>
        <TableRow>
          <TableHead>Severity</TableHead>
          <TableHead>Where</TableHead>
          <TableHead>Rule</TableHead>
          <TableHead>Finding</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {findings.map((finding, index) => (
          <TableRow key={findingKey(finding, index)} data-testid="finding-row">
            <TableCell className="align-top">
              <SeverityBadge severity={finding.severity} />
            </TableCell>
            <TableCell className="max-w-56 align-top">
              <TruncatedPath path={location(finding)} focusable={false} />
            </TableCell>
            <TableCell className="align-top">
              <Rule finding={finding} />
            </TableCell>
            <TableCell className="min-w-56 align-top whitespace-normal">
              <Message finding={finding} sources={sources} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function FindingCards({
  findings,
  label,
  sources,
}: {
  findings: Finding[];
  label: string;
  sources?: number;
}) {
  return (
    <ul aria-label={label} className="flex flex-col gap-2">
      {findings.map((finding, index) => (
        <li
          key={findingKey(finding, index)}
          data-testid="finding-card"
          className="flex min-w-0 flex-col gap-1.5 rounded-lg border bg-card px-3 py-2 text-meta"
        >
          <span className="flex min-w-0 flex-wrap items-center gap-2">
            <SeverityBadge severity={finding.severity} />
            <Rule finding={finding} />
          </span>
          <TruncatedPath
            path={location(finding)}
            focusable={false}
            className="text-foreground-secondary"
          />
          <Message finding={finding} sources={sources} />
        </li>
      ))}
    </ul>
  );
}

/** The checks once each: a merged report repeats every source's (same path, kind and tool). */
export function uniqueChecks(checks: Check[]): Check[] {
  const seen = new Set<string>();
  return checks.filter((check) => {
    const key = [check.path, check.kind, check.tool ?? ""].join("\n");
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/** What was checked where, as a grid that lines up (path, kind, then tool and config or why it
 * was skipped); the root reads "repo root" (design-language.md → Content rules). */
function Checked({ checks }: { checks: Check[] }) {
  const unique = uniqueChecks(checks);
  if (unique.length === 0) return null;
  return (
    <section aria-label="Checked" className="flex flex-col gap-1.5">
      <h3 className="text-caption font-medium text-muted-foreground">Checked</h3>
      <ul className="flex flex-col gap-2 text-meta sm:grid sm:grid-cols-[minmax(0,auto)_auto_minmax(0,1fr)] sm:gap-x-4 sm:gap-y-1">
        {unique.map((check) => (
          <li
            key={[check.path, check.kind, check.tool ?? ""].join(" ")}
            data-testid="scan-check"
            data-status={check.status}
            className="flex min-w-0 flex-col sm:col-span-3 sm:grid sm:grid-cols-subgrid sm:items-baseline"
          >
            <span className="min-w-0">
              <TruncatedPath path={check.path} focusable={false} />
            </span>
            <span className="text-foreground-secondary">{check.kind}</span>
            <span
              className={
                check.status === "ran" ? "text-foreground-secondary" : "text-status-waiting"
              }
            >
              {checkLine(check)}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The reports a merged report was made from, by id (mono), with how many findings each gave. */
function MergedFrom({ sources }: { sources: Source[] }) {
  return (
    <p data-testid="merged-from" className="text-meta text-foreground-secondary">
      Merged from {sources.length === 1 ? "1 source" : `${sources.length} sources`}:{" "}
      {sources.map((source, i) => (
        <span key={source.id}>
          {i > 0 ? ", " : null}
          <span className="font-mono text-foreground">{source.id}</span> (
          {formatCount(source.findings)})
        </span>
      ))}
    </p>
  );
}

/**
 * A findings report: counts by severity, the sources of a merged report, what was checked
 * where, then the findings, most severe first (a table from `md`, cards below), the first
 * `FINDINGS_SHOWN` then "Show all". A merged report adds each finding's confidence and the
 * sources that found it.
 */
export function FindingsView({ report, label }: { report: FindingsReport; label: string }) {
  const [all, setAll] = useState(false);
  const listId = useId();
  const findings = sortFindings(report.findings);
  const shown = all ? findings : findings.slice(0, FINDINGS_SHOWN);
  const total = SEVERITIES.reduce((sum, s) => sum + (report.counts[s] ?? 0), 0);
  const scanner = SCANNER_LABEL[report.scanner];
  const sources = report.sources ? report.sources.length : undefined;
  return (
    <div data-testid="findings-view" className="flex min-w-0 flex-col gap-4">
      <SeverityCounts counts={report.counts} />
      {report.sources?.length ? <MergedFrom sources={report.sources} /> : null}
      <Checked checks={report.checks} />
      {report.db_as_of ? (
        <p className="text-caption text-muted-foreground">
          Vulnerability database from <RelativeTime iso={report.db_as_of} />
        </p>
      ) : null}
      {findings.length === 0 ? (
        <EmptyState icon={ShieldCheckIcon} message={`${scanner}: no findings.`} />
      ) : (
        // A table where this box is 720 px or wider, cards below: by the pane, not the screen.
        <div id={listId} className="@container flex min-w-0 flex-col gap-2">
          <div className="hidden @min-[720px]:block">
            <FindingsTable findings={shown} label={label} sources={sources} />
          </div>
          <div className="@min-[720px]:hidden">
            <FindingCards findings={shown} label={label} sources={sources} />
          </div>
          {report.truncated ? (
            <p className="text-caption text-muted-foreground">
              Showing the {formatCount(findings.length)} most severe of {formatCount(total)}{" "}
              findings.
            </p>
          ) : null}
          {findings.length > FINDINGS_SHOWN ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="w-fit"
              aria-expanded={all}
              aria-controls={listId}
              onClick={() => setAll((a) => !a)}
            >
              {all ? "Show fewer" : `Show all ${formatCount(findings.length)}`}
            </Button>
          ) : null}
        </div>
      )}
    </div>
  );
}
