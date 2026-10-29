"use client";

import { useQuery } from "@tanstack/react-query";

import { apiBaseUrl, createApiClient } from "@/api/client";
import { AddFilter, FilterChip, FilterChoices, type FilterOption } from "@/components/filters";
import { Button } from "@/components/ui/button";

import { useTemplates } from "@/api/queries";

import { isFiltered, TEMPLATE_OPTIONS, type RunsQuery } from "./filters";
import { repoLabel } from "./summaries";

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

/** Narrow the runs list by template and repo (the view tabs pick the status): a chip per filter
 * that is on, then "+ Filter" (design-language.md → Components). The filters live in the URL. */
export function RunFiltersBar({
  filters,
  onChange,
  workspaceId,
  baseUrl = apiBaseUrl(),
}: {
  filters: RunsQuery;
  onChange: (filters: RunsQuery) => void;
  workspaceId: string;
  baseUrl?: string;
}) {
  const repos = useRepoOptions(workspaceId, baseUrl);
  const templates = useTemplates({ baseUrl });
  const templateOptions =
    templates.data?.map((t) => ({ id: t.id, label: t.name })) ?? TEMPLATE_OPTIONS;
  const repoOptions = repos.data
    ? [...new Set([...(filters.repo ? [filters.repo] : []), ...repos.data])]
    : filters.repo
      ? [filters.repo]
      : null;
  const templateName =
    templateOptions.find((t) => t.id === filters.template)?.label ?? filters.template;

  const options: FilterOption[] = [
    {
      id: "template",
      label: "Template",
      control: (done) => (
        <FilterChoices
          label="Template"
          choices={templateOptions}
          value={filters.template}
          onPick={(template) => {
            onChange({ ...filters, template });
            done();
          }}
        />
      ),
    },
  ];
  if (repoOptions) {
    options.push({
      id: "repo",
      label: "Repository",
      control: (done) => (
        <FilterChoices
          label="Repository"
          mono
          choices={repoOptions.map((url) => ({ id: url, label: repoLabel(url) }))}
          value={filters.repo}
          onPick={(repo) => {
            onChange({ ...filters, repo });
            done();
          }}
        />
      ),
    });
  }

  return (
    <div role="group" aria-label="Filters" className="flex flex-wrap items-center gap-2">
      {filters.template ? (
        <FilterChip
          label="Template"
          value={templateName}
          onRemove={() => onChange({ ...filters, template: null })}
        />
      ) : null}
      {filters.repo ? (
        <FilterChip
          label="Repository"
          value={repoLabel(filters.repo)}
          mono
          onRemove={() => onChange({ ...filters, repo: null })}
        />
      ) : null}
      <AddFilter options={options} />
      {isFiltered(filters) ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => onChange({ ...filters, template: null, repo: null })}
        >
          Clear filters
        </Button>
      ) : null}
    </div>
  );
}
