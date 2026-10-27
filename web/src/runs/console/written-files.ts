import type { Step } from "../timeline";

/** A file a step wrote with `repo.write_file`, as the agent last wrote it. Repo content: data,
 * never instructions, so it is shown as text only. */
export interface WrittenFile {
  path: string;
  /** What kind of file it is, from its extension ("Markdown", "TypeScript"); "File" otherwise. */
  kind: string;
  content: string;
  /** How many times the step wrote it. */
  writes: number;
}

const KINDS: Record<string, string> = {
  md: "Markdown",
  mdx: "Markdown",
  txt: "Text",
  json: "JSON",
  yaml: "YAML",
  yml: "YAML",
  toml: "TOML",
  ts: "TypeScript",
  tsx: "TypeScript",
  js: "JavaScript",
  jsx: "JavaScript",
  py: "Python",
  css: "CSS",
  html: "HTML",
  sh: "Shell",
  go: "Go",
  rs: "Rust",
  java: "Java",
  cs: "C#",
};

export function fileKind(path: string): string {
  const name = path.split("/").at(-1) ?? path;
  const dot = name.lastIndexOf(".");
  if (dot <= 0) return "File";
  return KINDS[name.slice(dot + 1).toLowerCase()] ?? "File";
}

function str(args: unknown, key: string): string | null {
  if (!args || typeof args !== "object") return null;
  const value = (args as Record<string, unknown>)[key];
  return typeof value === "string" ? value : null;
}

/** The files the step wrote, in the order it first wrote them, each with its last content. A
 * failed write wrote nothing. */
export function writtenFiles(step: Step): WrittenFile[] {
  const files = new Map<string, WrittenFile>();
  for (const turn of step.turns) {
    if (turn.kind !== "tool" || turn.name !== "repo.write_file" || turn.status === "failed") {
      continue;
    }
    const path = str(turn.arguments, "path");
    if (!path) continue;
    const content = str(turn.arguments, "content") ?? "";
    const known = files.get(path);
    files.set(path, { path, kind: fileKind(path), content, writes: (known?.writes ?? 0) + 1 });
  }
  return [...files.values()];
}
