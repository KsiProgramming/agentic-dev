"use client";

import { ChevronLeftIcon, PlusIcon, XIcon } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

/**
 * A filter that is on (design-language.md → Components → Filter chip): `muted` fill, the
 * filter's name, its value in `foreground` weight 500, and a button that removes it.
 */
export function FilterChip({
  label,
  value,
  onRemove,
  mono = false,
}: {
  label: string;
  value: ReactNode;
  onRemove: () => void;
  /** The value is an id or a path. */
  mono?: boolean;
}) {
  return (
    <span
      data-testid="filter-chip"
      className="inline-flex h-7 max-w-full items-center gap-1.5 rounded-md bg-muted pr-0.5 pl-2 text-meta"
    >
      <span className="shrink-0 text-muted-foreground">{label}:</span>
      <span className={cn("min-w-0 truncate font-medium text-foreground", mono && "font-mono")}>
        {value}
      </span>
      <button
        type="button"
        aria-label={`Remove the ${label.toLowerCase()} filter`}
        onClick={onRemove}
        className="flex size-6 shrink-0 items-center justify-center rounded-sm text-foreground-secondary hover:bg-background hover:text-foreground"
      >
        <XIcon aria-hidden="true" className="size-3.5" />
      </button>
    </span>
  );
}

/** One filter "+ Filter" offers: its name and the control that sets it, which calls `done`. */
export interface FilterOption {
  id: string;
  label: string;
  control: (done: () => void) => ReactNode;
}

/**
 * The dashed "+ Filter" button (design-language.md → Components): a popover listing the
 * filters; picking one shows its control in the same popover, which closes once it is set.
 */
export function AddFilter({ options }: { options: FilterOption[] }) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  const option = options.find((o) => o.id === active) ?? null;
  const close = () => {
    setOpen(false);
    setActive(null);
  };
  if (options.length === 0) return null;
  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setActive(null);
      }}
    >
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="border-dashed border-border-strong text-foreground-secondary"
        >
          <PlusIcon aria-hidden="true" data-icon="inline-start" />
          Filter
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72 p-0">
        {option ? (
          <div className="flex flex-col">
            <div className="flex items-center gap-1 border-b bg-surface-subtle px-1 py-1">
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                aria-label="Back to the filters"
                onClick={() => setActive(null)}
              >
                <ChevronLeftIcon aria-hidden="true" />
              </Button>
              <span className="text-caption font-medium text-muted-foreground">{option.label}</span>
            </div>
            {option.control(close)}
          </div>
        ) : (
          <Command>
            <CommandList>
              <CommandGroup heading="Filter by">
                {options.map((o) => (
                  <CommandItem key={o.id} value={o.label} onSelect={() => setActive(o.id)}>
                    {o.label}
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        )}
      </PopoverContent>
    </Popover>
  );
}

/** A filter's control that is a list of choices, searchable when it is long. */
export function FilterChoices({
  label,
  choices,
  value,
  onPick,
  mono = false,
}: {
  label: string;
  choices: readonly { id: string; label: string }[];
  value: string | null;
  onPick: (id: string) => void;
  mono?: boolean;
}) {
  return (
    <Command label={label}>
      {choices.length > 7 ? <CommandInput placeholder={`Search ${label.toLowerCase()}…`} /> : null}
      <CommandList>
        <CommandEmpty>Nothing matches.</CommandEmpty>
        <CommandGroup>
          {choices.map((choice) => (
            <CommandItem
              key={choice.id}
              value={`${choice.label} ${choice.id}`}
              data-checked={choice.id === value || undefined}
              onSelect={() => onPick(choice.id)}
              className={cn(mono && "font-mono", choice.id === value && "font-medium")}
            >
              {choice.label}
            </CommandItem>
          ))}
        </CommandGroup>
      </CommandList>
    </Command>
  );
}
