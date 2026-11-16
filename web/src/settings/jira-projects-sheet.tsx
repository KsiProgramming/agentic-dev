"use client";

import { FolderKanbanIcon, LoaderCircleIcon } from "lucide-react";
import { useId, useState } from "react";
import { toast } from "sonner";

import {
  useJiraProjects,
  usePutJiraProjects,
  type JiraProject,
  type JiraSite,
} from "@/api/queries";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useDebounced } from "@/lib/use-debounced";
import { MD_UP, useMediaQuery } from "@/lib/use-media-query";

interface SheetProps {
  site: JiraSite;
  workspaceId: string;
  baseUrl?: string;
  onOpenChange: (open: boolean) => void;
}

/**
 * Picks the projects of one Jira site the workspace may use. Atlassian's consent covers a whole
 * site, so this list is the platform's own limit: agents reach no other project. A side sheet
 * from 768 px, a full-height bottom sheet below.
 */
export function JiraProjectsSheet({ open, ...props }: SheetProps & { open: boolean }) {
  const wide = useMediaQuery(MD_UP);
  return (
    <Sheet open={open} onOpenChange={props.onOpenChange}>
      <SheetContent
        side={wide ? "right" : "bottom"}
        className="data-[side=bottom]:h-svh"
        size="sm"
        data-testid="jira-projects-sheet"
      >
        {/* Mounted only while open, so a closed sheet asks Jira for nothing. */}
        <SheetBody {...props} />
      </SheetContent>
    </Sheet>
  );
}

function SheetBody({ site, workspaceId, baseUrl, onOpenChange }: SheetProps) {
  const searchId = useId();
  const [search, setSearch] = useState("");
  const query = useDebounced(search.trim(), 200);
  // Kept by id with their names, so a pick that the search no longer lists is still counted.
  const [selected, setSelected] = useState<Map<string, JiraProject>>(
    () => new Map(site.projects.map((p) => [p.id, p])),
  );
  const projects = useJiraProjects({ workspaceId, cloudId: site.cloud_id, query, baseUrl });
  const save = usePutJiraProjects({ workspaceId, baseUrl });

  function toggle(project: JiraProject, on: boolean) {
    setSelected((current) => {
      const next = new Map(current);
      if (on) next.set(project.id, project);
      else next.delete(project.id);
      return next;
    });
  }

  const list = (() => {
    if (projects.isPending) return <LoadingState rows={5} label="Loading projects…" />;
    if (projects.isError) {
      return (
        <ErrorState message={projects.error.message} onRetry={() => void projects.refetch()} />
      );
    }
    if (projects.data.projects.length === 0) {
      return (
        <EmptyState
          icon={FolderKanbanIcon}
          message={query ? "No project matches." : "This site has no projects you can see."}
        />
      );
    }
    return (
      <>
        <ul
          className="flex flex-col divide-y divide-divider rounded-lg border"
          aria-label="Projects"
        >
          {projects.data.projects.map((project) => (
            <ProjectRow
              key={project.id}
              project={project}
              checked={selected.has(project.id)}
              onToggle={toggle}
            />
          ))}
        </ul>
        {projects.data.next_cursor !== null && projects.data.next_cursor !== undefined ? (
          <p className="text-caption text-muted-foreground">
            Showing the first {projects.data.projects.length}. Search to find the others.
          </p>
        ) : null}
      </>
    );
  })();

  return (
    <>
      <SheetHeader>
        <SheetTitle>Projects of {site.name}</SheetTitle>
        <SheetDescription>
          Agents can read and, after an approval, change only the projects picked here.
        </SheetDescription>
      </SheetHeader>
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4">
        <label htmlFor={searchId} className="sr-only">
          Search projects
        </label>
        <Input
          id={searchId}
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search by key or name"
          autoComplete="off"
        />
        {list}
      </div>
      {save.error ? (
        <Alert variant="destructive" className="mx-4 w-auto">
          <AlertDescription>{save.error.message}</AlertDescription>
        </Alert>
      ) : null}
      <SheetFooter className="flex-row items-center justify-end gap-2">
        <span className="mr-auto text-meta text-foreground-secondary" aria-live="polite">
          {selected.size} selected
        </span>
        <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
          Cancel
        </Button>
        <Button
          type="button"
          disabled={save.isPending}
          onClick={() =>
            save.mutate(
              { cloudId: site.cloud_id, projectIds: [...selected.keys()] },
              {
                onSuccess: () => {
                  toast.success("Projects saved.");
                  onOpenChange(false);
                },
              },
            )
          }
        >
          {save.isPending ? (
            <LoaderCircleIcon
              aria-hidden="true"
              data-icon="inline-start"
              className="motion-safe:animate-spin"
            />
          ) : null}
          {save.isPending ? "Saving…" : "Save projects"}
        </Button>
      </SheetFooter>
    </>
  );
}

function ProjectRow({
  project,
  checked,
  onToggle,
}: {
  project: JiraProject;
  checked: boolean;
  onToggle: (project: JiraProject, on: boolean) => void;
}) {
  const id = useId();
  return (
    <li
      data-selected={checked || undefined}
      className="flex min-w-0 items-center gap-3 px-3 py-2 text-meta data-selected:bg-surface-subtle"
    >
      <Checkbox
        id={id}
        checked={checked}
        onCheckedChange={(on) => onToggle(project, on === true)}
      />
      {/* Project names come from Jira: shown as text. */}
      <label htmlFor={id} className="flex min-w-0 flex-1 items-baseline gap-2">
        <span className="shrink-0 font-mono text-caption text-foreground-secondary">
          {project.key}
        </span>
        <span className="truncate font-medium text-foreground">{project.name}</span>
      </label>
    </li>
  );
}
