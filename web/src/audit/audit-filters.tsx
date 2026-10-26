"use client";

import { CircleAlertIcon, XIcon } from "lucide-react";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";

import { AUDIT_CATEGORIES, type AuditCategory } from "./actions";
import { isAuditFiltered, isRunId, NO_AUDIT_FILTERS, type AuditFilters } from "./filters";

/** A run id, applied on Enter or when the field loses focus; empty clears it. Keyed by `value`,
 * so a change from the URL starts it again. */
function RunFilter({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (run: string | null) => void;
}) {
  const id = useId();
  const errorId = useId();
  const [draft, setDraft] = useState(value ?? "");
  const [invalid, setInvalid] = useState(false);

  const apply = () => {
    const run = draft.trim().toLowerCase();
    if (run === "") {
      setInvalid(false);
      if (value !== null) onChange(null);
    } else if (isRunId(run)) {
      setInvalid(false);
      if (run !== value) onChange(run);
    } else {
      setInvalid(true);
    }
  };

  return (
    <form
      className="flex flex-col gap-1"
      onSubmit={(e) => {
        e.preventDefault();
        apply();
      }}
    >
      <Label htmlFor={id} className="sr-only">
        Run id
      </Label>
      <Input
        id={id}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={apply}
        placeholder="Run id"
        spellCheck={false}
        autoComplete="off"
        aria-invalid={invalid || undefined}
        aria-describedby={invalid ? errorId : undefined}
        className="h-8 w-full font-mono text-xs sm:w-80"
      />
      {invalid ? (
        <p id={errorId} className="flex items-center gap-1 text-xs text-destructive">
          <CircleAlertIcon aria-hidden="true" className="size-3.5" />
          Enter a full run id.
        </p>
      ) : null}
    </form>
  );
}

/** Narrow the audit log by category, run and dates. */
export function AuditFiltersBar({
  filters,
  onChange,
}: {
  filters: AuditFilters;
  onChange: (filters: AuditFilters) => void;
}) {
  const categoryId = useId();
  const fromId = useId();
  const toId = useId();
  return (
    <div role="group" aria-label="Filters" className="flex flex-wrap items-start gap-2">
      <Label htmlFor={categoryId} className="sr-only">
        Category
      </Label>
      <NativeSelect
        id={categoryId}
        size="sm"
        value={filters.category ?? ""}
        onChange={(e) =>
          onChange({ ...filters, category: (e.target.value || null) as AuditCategory | null })
        }
      >
        <NativeSelectOption value="">All activity</NativeSelectOption>
        {AUDIT_CATEGORIES.map((c) => (
          <NativeSelectOption key={c.id} value={c.id}>
            {c.label}
          </NativeSelectOption>
        ))}
      </NativeSelect>
      <RunFilter
        key={filters.run ?? ""}
        value={filters.run}
        onChange={(run) => onChange({ ...filters, run })}
      />
      <div className="flex items-center gap-1.5">
        <Label htmlFor={fromId} className="text-xs text-muted-foreground">
          From
        </Label>
        <Input
          id={fromId}
          type="date"
          value={filters.from ?? ""}
          max={filters.to ?? undefined}
          onChange={(e) => onChange({ ...filters, from: e.target.value || null })}
          className="h-8 w-auto text-xs"
        />
        <Label htmlFor={toId} className="text-xs text-muted-foreground">
          To
        </Label>
        <Input
          id={toId}
          type="date"
          value={filters.to ?? ""}
          min={filters.from ?? undefined}
          onChange={(e) => onChange({ ...filters, to: e.target.value || null })}
          className="h-8 w-auto text-xs"
        />
      </div>
      {isAuditFiltered(filters) ? (
        <Button type="button" variant="ghost" size="sm" onClick={() => onChange(NO_AUDIT_FILTERS)}>
          <XIcon aria-hidden="true" data-icon="inline-start" />
          Clear filters
        </Button>
      ) : null}
    </div>
  );
}
