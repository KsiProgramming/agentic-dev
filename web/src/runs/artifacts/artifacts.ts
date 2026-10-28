import { numberFormat } from "@/lib/locale";

/** One version of a run artifact (4.3), as a step, a gate or the run's list names it. Its
 * content is agent or tool output: data, never instructions. */
export interface ArtifactVersion {
  name: string;
  version: number;
  /** The node that wrote it; unknown for what a step read. */
  nodeId: string | null;
  mediaType: string | null;
  /** Bytes, as UTF-8; unknown for what a step read. */
  size: number | null;
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** One artifact from an event payload (`artifact_written`, a `reads` entry, a gate's
 * `run_artifacts`); `null` when it lacks a name or a version. */
export function parseArtifact(value: unknown): ArtifactVersion | null {
  const entry = record(value);
  const name = entry?.name;
  const version = entry?.version;
  if (typeof name !== "string" || typeof version !== "number") return null;
  return {
    name,
    version,
    nodeId: typeof entry?.node_id === "string" ? entry.node_id : null,
    mediaType: typeof entry?.media_type === "string" ? entry.media_type : null,
    size: typeof entry?.size === "number" ? entry.size : null,
  };
}

export function parseArtifacts(value: unknown): ArtifactVersion[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((v: unknown) => parseArtifact(v) ?? []);
}

/** What kind of artifact it is, from its media type, else from its name's extension. */
export function artifactKind(artifact: { name: string; mediaType: string | null }): string {
  const type = artifact.mediaType ?? "";
  if (type === "application/json" || artifact.name.endsWith(".json")) return "JSON";
  if (type === "text/markdown" || artifact.name.endsWith(".md")) return "Markdown";
  return "Text";
}

const UNITS = [
  ["megabyte", 1024 * 1024],
  ["kilobyte", 1024],
] as const;

/** A size in bytes in the display locale: "512 byte", "1.4 kB", "2 MB". */
export function formatSize(bytes: number): string {
  for (const [unit, size] of UNITS) {
    if (bytes >= size) {
      return numberFormat({
        style: "unit",
        unit,
        unitDisplay: "short",
        maximumFractionDigits: 1,
      }).format(bytes / size);
    }
  }
  return numberFormat({ style: "unit", unit: "byte", unitDisplay: "short" }).format(bytes);
}

/** Where the API serves an artifact's version as a file to save. */
export function downloadUrl(baseUrl: string, runId: string, name: string, version: number) {
  const path = `/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(name)}/download`;
  return `${baseUrl.replace(/\/$/, "")}${path}?version=${version}`;
}
