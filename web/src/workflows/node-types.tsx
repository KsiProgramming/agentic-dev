"use client";

import { useQuery } from "@tanstack/react-query";
import {
  BotIcon,
  BoxIcon,
  LayersIcon,
  ListOrderedIcon,
  MergeIcon,
  RepeatIcon,
  ShieldCheckIcon,
  SignpostIcon,
  SplitIcon,
  WorkflowIcon,
  WrenchIcon,
  type LucideIcon,
} from "lucide-react";

import { apiBaseUrl, createApiClient } from "@/api/client";
import { ApiError } from "@/api/errors";
import type { components } from "@/api/schema";

/**
 * The node types the engine knows (5.3), each described by its manifest: the builder's palette
 * and its cards are drawn from them, so a primitive the engine adds needs no change here. A
 * workspace's composites (6.6) follow the primitives, each a `subflow` pinned to its latest
 * published version, under "Workspace nodes".
 */

export type NodeManifest = components["schemas"]["NodeManifest"];

export function nodeTypesKey(workspaceId?: string) {
  return workspaceId ? (["node-types", workspaceId] as const) : (["node-types"] as const);
}

/** `GET /node-types`: every primitive's manifest, in palette order, then, with `workspaceId`,
 * the workspace's composites. The primitives change only with an engine release; the composites
 * when one is published, which refreshes them. */
export function useNodeTypes(baseUrl = apiBaseUrl(), workspaceId?: string) {
  return useQuery({
    queryKey: nodeTypesKey(workspaceId),
    queryFn: async () => {
      let result;
      try {
        result = await createApiClient(baseUrl).GET("/node-types", {
          params: { query: workspaceId ? { workspace_id: workspaceId } : {} },
        });
      } catch (err) {
        throw err instanceof TypeError ? new Error("Could not reach the API.") : err;
      }
      const { data, error, response } = result;
      if (!data) throw new ApiError(response.status, error, "Could not load the node types");
      return data;
    },
    staleTime: Infinity,
  });
}

/** How the palette names an entry: the kind for a primitive, `composite:<workflow id>` for a
 * workspace's composite, which shares the `subflow` kind. */
export function paletteKey(manifest: NodeManifest): string {
  return manifest.composite ? `composite:${manifest.composite.workflow_id}` : manifest.kind;
}

/** The manifest the palette entry `key` names (`paletteKey`). */
export function manifestByKey(manifests: NodeManifest[], key: string): NodeManifest | undefined {
  return manifests.find((m) => paletteKey(m) === key);
}

// The icons manifests name today. A name not here is drawn as a box, so a new primitive still
// shows; adding its icon here is only cosmetic.
const ICONS: Record<string, LucideIcon> = {
  bot: BotIcon,
  wrench: WrenchIcon,
  "shield-check": ShieldCheckIcon,
  "list-ordered": ListOrderedIcon,
  layers: LayersIcon,
  split: SplitIcon,
  signpost: SignpostIcon,
  repeat: RepeatIcon,
  merge: MergeIcon,
  workflow: WorkflowIcon,
};

/** A manifest's icon, by its lucide name; a box for a name this app does not have. */
export function ManifestIcon({ name, className }: { name: string; className?: string }) {
  const Icon = ICONS[name] ?? BoxIcon;
  return <Icon aria-hidden="true" className={className} />;
}

const CATEGORIES: Record<string, string> = {
  step: "Steps",
  flow: "Flow",
  combine: "Combine",
  workspace: "Workspace nodes",
};

export interface PaletteGroup {
  label: string;
  items: NodeManifest[];
}

/** The manifests by category, in the order above; an unknown category comes last, as "Other". */
export function paletteGroups(manifests: NodeManifest[]): PaletteGroup[] {
  const order = Object.keys(CATEGORIES);
  const rank = (category: string) => {
    const i = order.indexOf(category);
    return i < 0 ? order.length : i;
  };
  const groups = new Map<string, NodeManifest[]>();
  for (const m of manifests) {
    const label = CATEGORIES[m.category] ?? "Other";
    groups.set(label, [...(groups.get(label) ?? []), m]);
  }
  return [...groups.entries()]
    .map(([label, items]) => ({ label, items }))
    .sort((a, b) => rank(a.items[0].category) - rank(b.items[0].category));
}
