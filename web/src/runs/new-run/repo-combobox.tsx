"use client";

import {
  CheckIcon,
  ChevronsUpDownIcon,
  ExternalLinkIcon,
  GitBranchIcon,
  LockIcon,
} from "lucide-react";
import { useState } from "react";

import type { Repo } from "@/api/queries";
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

/** Picks one of the workspace's repos: a button that opens a searchable list (type to filter,
 * arrows, Enter). `value` is the repo's `html_url`. */
export function RepoCombobox({
  id,
  repos,
  value,
  onChange,
  manageUrl,
  invalid,
  describedBy,
  disabled,
}: {
  id: string;
  repos: Repo[];
  value: string;
  onChange: (htmlUrl: string) => void;
  /** The installation's settings page on GitHub, where more repos can be added. */
  manageUrl?: string | null;
  invalid?: boolean;
  describedBy?: string;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const selected = repos.find((r) => r.html_url === value);
  const listId = `${id}-list`;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
          disabled={disabled}
          className="w-full justify-between font-normal"
        >
          {selected ? (
            <span className="flex min-w-0 items-center gap-2">
              <span className="truncate font-mono">{selected.full_name}</span>
              {selected.private ? (
                <LockIcon aria-label="Private" className="size-3.5 shrink-0" />
              ) : null}
            </span>
          ) : (
            <span className="text-muted-foreground">Select a repository</span>
          )}
          <ChevronsUpDownIcon aria-hidden="true" className="size-4 shrink-0 opacity-60" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-(--radix-popover-trigger-width) p-0" align="start">
        <Command>
          <CommandInput placeholder="Search repositories…" />
          <CommandList id={listId}>
            <CommandEmpty>No repository matches.</CommandEmpty>
            <CommandGroup>
              {repos.map((repo) => (
                <CommandItem
                  key={repo.id}
                  value={repo.full_name}
                  onSelect={() => {
                    onChange(repo.html_url);
                    setOpen(false);
                  }}
                >
                  <CheckIcon
                    aria-hidden="true"
                    className={cn("size-4", repo.html_url === value ? "opacity-100" : "opacity-0")}
                  />
                  <span className="min-w-0 flex-1 truncate font-mono">{repo.full_name}</span>
                  {repo.private ? (
                    <LockIcon aria-label="Private" className="size-3.5 shrink-0" />
                  ) : null}
                  <span className="flex shrink-0 items-center gap-1 font-mono text-xs text-muted-foreground">
                    <GitBranchIcon aria-hidden="true" className="size-3" />
                    {repo.default_branch}
                  </span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
          {manageUrl ? (
            <div className="border-t p-1">
              <Button asChild variant="ghost" size="sm" className="w-full justify-start">
                <a href={manageUrl} target="_blank" rel="noreferrer">
                  <ExternalLinkIcon aria-hidden="true" data-icon="inline-start" />
                  Add repos on GitHub
                  <span className="sr-only">(opens in a new tab)</span>
                </a>
              </Button>
            </div>
          ) : null}
        </Command>
      </PopoverContent>
    </Popover>
  );
}
