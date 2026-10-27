"use client";

import { useQuery } from "@tanstack/react-query";
import { XIcon } from "lucide-react";
import { useId } from "react";

import { apiBaseUrl, createApiClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";

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

/** Narrow the runs list by template and repo (the view tabs pick the status). */
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
  const templateId = useId();
  const repoId = useId();
  const repos = useRepoOptions(workspaceId, baseUrl);
  const templates = useTemplates({ baseUrl });
  const templateOptions =
    templates.data?.map((t) => ({ id: t.id, label: t.name })) ?? TEMPLATE_OPTIONS;
  const repoOptions = repos.data
    ? [...new Set([...(filters.repo ? [filters.repo] : []), ...repos.data])]
    : filters.repo
      ? [filters.repo]
      : null;

  return (
    <div role="group" aria-label="Filters" className="flex flex-wrap items-center gap-2">
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
        {templateOptions.map((t) => (
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
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => onChange({ ...filters, template: null, repo: null })}
        >
          <XIcon aria-hidden="true" data-icon="inline-start" />
          Clear filters
        </Button>
      ) : null}
    </div>
  );
}
