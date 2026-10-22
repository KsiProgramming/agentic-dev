"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDownIcon, XIcon } from "lucide-react";
import { useId } from "react";

import { apiBaseUrl, createApiClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Label } from "@/components/ui/label";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";

import { isFiltered, NO_FILTERS, TEMPLATE_OPTIONS, type RunFilters } from "./filters";
import { API_RUN_STATUSES, repoLabel, statusLabel } from "./summaries";

/** The repo URLs runs can be filtered by: the repos the GitHub App reaches, or `null` when
 * GitHub is not connected (the filter is then hidden). */
function useRepoOptions(workspaceId: string, baseUrl: string) {
  return useQuery({
    queryKey: ["repos", workspaceId],
    queryFn: async () => {
      const { data } = await createApiClient(baseUrl).GET("/workspaces/{workspace_id}/repos", {
        params: { path: { workspace_id: workspaceId } },
      });
      return data ? data.map((r) => r.html_url) : null;
    },
    retry: false,
  });
}

function StatusFilter({
  value,
  onChange,
}: {
  value: RunFilters["status"];
  onChange: (status: RunFilters["status"]) => void;
}) {
  const summary =
    value.length === 0
      ? "Any status"
      : value.length === 1
        ? statusLabel(value[0]!)
        : `${value.length} statuses`;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="outline" size="sm" aria-label={`Status: ${summary}`}>
          {summary}
          <ChevronDownIcon aria-hidden="true" data-icon="inline-end" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        {API_RUN_STATUSES.map((status) => (
          <DropdownMenuCheckboxItem
            key={status}
            checked={value.includes(status)}
            // Keep the menu open to pick several.
            onSelect={(e) => e.preventDefault()}
            onCheckedChange={(checked) =>
              onChange(API_RUN_STATUSES.filter((s) => (s === status ? checked : value.includes(s))))
            }
          >
            {statusLabel(status)}
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** Narrow the runs list by status, template and repo. */
export function RunFiltersBar({
  filters,
  onChange,
  workspaceId,
  baseUrl = apiBaseUrl(),
}: {
  filters: RunFilters;
  onChange: (filters: RunFilters) => void;
  workspaceId: string;
  baseUrl?: string;
}) {
  const templateId = useId();
  const repoId = useId();
  const repos = useRepoOptions(workspaceId, baseUrl);
  const repoOptions = repos.data
    ? [...new Set([...(filters.repo ? [filters.repo] : []), ...repos.data])]
    : filters.repo
      ? [filters.repo]
      : null;

  return (
    <div role="group" aria-label="Filters" className="flex flex-wrap items-center gap-2">
      <StatusFilter
        value={filters.status}
        onChange={(status) => onChange({ ...filters, status })}
      />
      <Label htmlFor={templateId} className="sr-only">
        Template
      </Label>
      <NativeSelect
        id={templateId}
        size="sm"
        value={filters.template ?? ""}
        onChange={(e) => onChange({ ...filters, template: e.target.value || null })}
      >
        <NativeSelectOption value="">Any template</NativeSelectOption>
        {TEMPLATE_OPTIONS.map((t) => (
          <NativeSelectOption key={t.id} value={t.id}>
            {t.label}
          </NativeSelectOption>
        ))}
      </NativeSelect>
      {repoOptions ? (
        <>
          <Label htmlFor={repoId} className="sr-only">
            Repo
          </Label>
          <NativeSelect
            id={repoId}
            size="sm"
            className="max-w-full"
            value={filters.repo ?? ""}
            onChange={(e) => onChange({ ...filters, repo: e.target.value || null })}
          >
            <NativeSelectOption value="">Any repo</NativeSelectOption>
            {repoOptions.map((url) => (
              <NativeSelectOption key={url} value={url}>
                {repoLabel(url)}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </>
      ) : null}
      {isFiltered(filters) ? (
        <Button type="button" variant="ghost" size="sm" onClick={() => onChange(NO_FILTERS)}>
          <XIcon aria-hidden="true" data-icon="inline-start" />
          Clear filters
        </Button>
      ) : null}
    </div>
  );
}
