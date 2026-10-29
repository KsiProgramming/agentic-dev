"use client";

import { CircleAlertIcon } from "lucide-react";
import { useId, useState } from "react";

import { shortId } from "@/components/display";
import { AddFilter, FilterChip, FilterChoices, type FilterOption } from "@/components/filters";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { dateFormat } from "@/lib/locale";

import { AUDIT_CATEGORIES, type AuditCategory } from "./actions";
import { isAuditFiltered, isRunId, NO_AUDIT_FILTERS, type AuditFilters } from "./filters";

/** A run id, applied on Enter or with Apply; it must be a full id. */
function RunFilter({ value, onApply }: { value: string | null; onApply: (run: string) => void }) {
  const id = useId();
  const errorId = useId();
  const [draft, setDraft] = useState(value ?? "");
  const [invalid, setInvalid] = useState(false);

  return (
    <form
      className="flex flex-col gap-2 p-3"
      onSubmit={(e) => {
        e.preventDefault();
        const run = draft.trim().toLowerCase();
        if (isRunId(run)) {
          setInvalid(false);
          onApply(run);
        } else {
          setInvalid(true);
        }
      }}
    >
      <Label htmlFor={id}>Run id</Label>
      <Input
        id={id}
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        placeholder="00000000-0000-…"
        spellCheck={false}
        autoComplete="off"
        aria-invalid={invalid || undefined}
        aria-describedby={invalid ? errorId : undefined}
        className="font-mono"
      />
      {invalid ? (
        <p id={errorId} className="flex items-center gap-1 text-caption text-status-failed">
          <CircleAlertIcon aria-hidden="true" className="size-3" />
          Enter a full run id.
        </p>
      ) : null}
      <Button type="submit" size="sm" className="self-end">
        Apply
      </Button>
    </form>
  );
}

/** From and to dates (either may be left empty), applied together. */
function DatesFilter({
  from,
  to,
  onApply,
}: {
  from: string | null;
  to: string | null;
  onApply: (from: string | null, to: string | null) => void;
}) {
  const fromId = useId();
  const toId = useId();
  const [start, setStart] = useState(from ?? "");
  const [end, setEnd] = useState(to ?? "");
  return (
    <form
      className="flex flex-col gap-2 p-3"
      onSubmit={(e) => {
        e.preventDefault();
        onApply(start || null, end || null);
      }}
    >
      <div className="grid grid-cols-2 gap-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={fromId}>From</Label>
          <Input
            id={fromId}
            type="date"
            value={start}
            max={end || undefined}
            onChange={(e) => setStart(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={toId}>To</Label>
          <Input
            id={toId}
            type="date"
            value={end}
            min={start || undefined}
            onChange={(e) => setEnd(e.target.value)}
          />
        </div>
      </div>
      <Button type="submit" size="sm" className="self-end">
        Apply
      </Button>
    </form>
  );
}

/** A `YYYY-MM-DD` day in the display locale ("Oct 20"), read as a calendar day (UTC). */
function day(iso: string): string {
  return dateFormat({ month: "short", day: "numeric", timeZone: "UTC" }).format(
    new Date(`${iso}T00:00:00Z`),
  );
}

function datesLabel(from: string | null, to: string | null): string {
  if (from && to) return `${day(from)} – ${day(to)}`;
  return from ? `From ${day(from)}` : `Until ${day(to!)}`;
}

/** Narrow the audit log by category, run and dates: a chip per filter that is on, then
 * "+ Filter" (design-language.md → Components). The filters live in the URL. */
export function AuditFiltersBar({
  filters,
  onChange,
}: {
  filters: AuditFilters;
  onChange: (filters: AuditFilters) => void;
}) {
  const category = AUDIT_CATEGORIES.find((c) => c.id === filters.category);
  const options: FilterOption[] = [
    {
      id: "category",
      label: "Category",
      control: (done) => (
        <FilterChoices
          label="Category"
          choices={AUDIT_CATEGORIES}
          value={filters.category}
          onPick={(id) => {
            onChange({ ...filters, category: id as AuditCategory });
            done();
          }}
        />
      ),
    },
    {
      id: "run",
      label: "Run",
      control: (done) => (
        <RunFilter
          value={filters.run}
          onApply={(run) => {
            onChange({ ...filters, run });
            done();
          }}
        />
      ),
    },
    {
      id: "dates",
      label: "Dates",
      control: (done) => (
        <DatesFilter
          from={filters.from}
          to={filters.to}
          onApply={(from, to) => {
            onChange({ ...filters, from, to });
            done();
          }}
        />
      ),
    },
  ];
  return (
    <div role="group" aria-label="Filters" className="flex flex-wrap items-center gap-2">
      {category ? (
        <FilterChip
          label="Category"
          value={category.label}
          onRemove={() => onChange({ ...filters, category: null })}
        />
      ) : null}
      {filters.run ? (
        <FilterChip
          label="Run"
          value={shortId(filters.run)}
          mono
          onRemove={() => onChange({ ...filters, run: null })}
        />
      ) : null}
      {filters.from || filters.to ? (
        <FilterChip
          label="Dates"
          value={datesLabel(filters.from, filters.to)}
          onRemove={() => onChange({ ...filters, from: null, to: null })}
        />
      ) : null}
      <AddFilter options={options} />
      {isAuditFiltered(filters) ? (
        <Button type="button" variant="ghost" size="sm" onClick={() => onChange(NO_AUDIT_FILTERS)}>
          Clear filters
        </Button>
      ) : null}
    </div>
  );
}
