"use client";

import { ExternalLinkIcon, ShieldCheckIcon } from "lucide-react";
import { useId, useState } from "react";

import { RelativeTime, StatTile } from "@/components/display";
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
  location,
  SCANNER_LABEL,
  SEVERITIES,
  SEVERITY_DISPLAY,
  sortFindings,
  type Check,
  type Finding,
  type FindingsReport,
  type Severity,
} from "./findings";

/** Rows shown before "Show all". */
export const FINDINGS_SHOWN = 50;

/** A severity as an icon and a word, in neutral colours: severity is not a run status. */
export function SeverityBadge({ severity }: { severity: Severity }) {
  const { label, icon: Icon } = SEVERITY_DISPLAY[severity];
  return (
    <Badge variant="outline" data-severity={severity}>
      <Icon aria-hidden="true" />
      {label}
    </Badge>
  );
}

function Rule({ finding }: { finding: Finding }) {
  if (!finding.help_url) return <span className="font-mono break-all">{finding.rule}</span>;
  return (
    <a
      href={finding.help_url}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1 font-mono break-all text-primary underline-offset-4 hover:underline"
    >
      {finding.rule}
      <ExternalLinkIcon aria-hidden="true" className="size-3.5 shrink-0" />
      <span className="sr-only">(opens the rule&apos;s page)</span>
    </a>
  );
}

/** The scanner's message, and for a dependency what version fixes it. Text, never HTML. */
function Message({ finding }: { finding: Finding }) {
  const fixed = finding.fixed_versions ?? [];
  return (
    <span className="flex min-w-0 flex-col gap-0.5">
      <span className="break-words">{finding.message}</span>
      {finding.category === "dependency" ? (
        <span className="text-caption text-muted-foreground">
          {fixed.length > 0 ? `Fixed in ${fixed.join(", ")}` : "No fixed version yet"}
          {finding.aliases?.length ? ` · ${finding.aliases.join(", ")}` : ""}
        </span>
      ) : null}
      {finding.config === "platform-default" ? (
        <span className="text-caption text-muted-foreground">
          Platform default rules (the repo configures no linter here)
        </span>
      ) : null}
    </span>
  );
}

function FindingsTable({ findings, label }: { findings: Finding[]; label: string }) {
  return (
    <Table aria-label={label} className="text-meta">
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>Severity</TableHead>
          <TableHead>Where</TableHead>
          <TableHead>Rule</TableHead>
          <TableHead>Finding</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {findings.map((finding) => (
          <TableRow key={finding.fingerprint} data-testid="finding-row">
            <TableCell className="align-top">
              <SeverityBadge severity={finding.severity} />
            </TableCell>
            <TableCell className="max-w-56 align-top font-mono break-all whitespace-normal">
              {location(finding)}
            </TableCell>
            <TableCell className="max-w-48 align-top whitespace-normal">
              <Rule finding={finding} />
            </TableCell>
            <TableCell className="min-w-56 align-top whitespace-normal">
              <Message finding={finding} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function FindingCards({ findings, label }: { findings: Finding[]; label: string }) {
  return (
    <ul aria-label={label} className="flex flex-col gap-2">
      {findings.map((finding) => (
        <li
          key={finding.fingerprint}
          data-testid="finding-card"
          className="flex min-w-0 flex-col gap-1.5 rounded-lg border bg-card px-3 py-2 text-meta"
        >
          <span className="flex min-w-0 flex-wrap items-center gap-2">
            <SeverityBadge severity={finding.severity} />
            <Rule finding={finding} />
          </span>
          <span className="font-mono break-all text-muted-foreground">{location(finding)}</span>
          <Message finding={finding} />
        </li>
      ))}
    </ul>
  );
}

/** What was checked where: one line per check, with why anything was skipped. */
function Checked({ checks }: { checks: Check[] }) {
  if (checks.length === 0) return null;
  return (
    <section aria-label="Checked" className="flex flex-col gap-1">
      <h3 className="text-caption font-medium text-muted-foreground">Checked</h3>
      <ul className="flex flex-col gap-0.5 text-meta">
        {checks.map((check) => (
          <li
            key={`${check.path} ${check.tool ?? check.kind}`}
            data-testid="scan-check"
            data-status={check.status}
            className="flex min-w-0 flex-wrap gap-x-2"
          >
            <span className="font-mono break-all">{check.path}</span>
            <span className="text-muted-foreground">{check.kind}</span>
            <span className={check.status === "ran" ? undefined : "text-muted-foreground"}>
              {checkLine(check)}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * A `scan.*` report: counts by severity, what was checked where, then the findings, most severe
 * first (a table from `md`, cards below), the first `FINDINGS_SHOWN` then "Show all".
 */
export function FindingsView({ report, label }: { report: FindingsReport; label: string }) {
  const [all, setAll] = useState(false);
  const listId = useId();
  const findings = sortFindings(report.findings);
  const shown = all ? findings : findings.slice(0, FINDINGS_SHOWN);
  const total = SEVERITIES.reduce((sum, s) => sum + (report.counts[s] ?? 0), 0);
  const scanner = SCANNER_LABEL[report.scanner];
  return (
    <div data-testid="findings-view" className="flex min-w-0 flex-col gap-4">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-5">
        {SEVERITIES.map((severity) => (
          <StatTile
            key={severity}
            label={SEVERITY_DISPLAY[severity].label}
            value={formatCount(report.counts[severity] ?? 0)}
          />
        ))}
      </div>
      <Checked checks={report.checks} />
      {report.db_as_of ? (
        <p className="text-caption text-muted-foreground">
          Vulnerability database from <RelativeTime iso={report.db_as_of} />
        </p>
      ) : null}
      {findings.length === 0 ? (
        <EmptyState icon={ShieldCheckIcon} message={`${scanner}: no findings.`} />
      ) : (
        <div id={listId} className="flex min-w-0 flex-col gap-2">
          <div className="hidden md:block">
            <FindingsTable findings={shown} label={label} />
          </div>
          <div className="md:hidden">
            <FindingCards findings={shown} label={label} />
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
