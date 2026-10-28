import {
  FilePenIcon,
  FileTextIcon,
  FolderTreeIcon,
  GitCommitHorizontalIcon,
  GitPullRequestIcon,
  KeyRoundIcon,
  PackageIcon,
  ScanSearchIcon,
  SearchIcon,
  ShieldAlertIcon,
  WrenchIcon,
  type LucideIcon,
} from "lucide-react";

import type { ToolTurn } from "../timeline";

/** How a tool call reads in the console: "Read `src/app.ts`", "Reading `src/app.ts`…". */
export interface ToolDescription {
  icon: LucideIcon;
  /** Past tense, for a finished call ("Read"). */
  done: string;
  /** Present tense, for a call in flight ("Reading"). */
  doing: string;
  /** What the call acted on (a path, a pattern, a message), shown in mono; may be empty. */
  target: string;
  /** Counts calls of this kind in a group summary: "read 3 files". */
  noun: [singular: string, plural: string];
  verb: string;
}

function arg(args: unknown, key: string): string {
  if (args && typeof args === "object" && key in args) {
    const value = (args as Record<string, unknown>)[key];
    if (typeof value === "string") return value;
  }
  return "";
}

/** The first string argument, for tools the console does not know. */
function firstString(args: unknown): string {
  if (!args || typeof args !== "object") return "";
  const value = Object.values(args as Record<string, unknown>).find((v) => typeof v === "string");
  return typeof value === "string" ? value : "";
}

function oneLine(text: string, max = 80): string {
  const line = text.split("\n")[0] ?? "";
  return line.length > max ? `${line.slice(0, max - 1)}…` : line;
}

/** How to show a tool call: its icon, verbs and target. */
export function describeTool(name: string, args: unknown): ToolDescription {
  switch (name) {
    case "repo.read_file":
      return {
        icon: FileTextIcon,
        done: "Read",
        doing: "Reading",
        target: arg(args, "path"),
        verb: "read",
        noun: ["file", "files"],
      };
    case "repo.list_files": {
      const path = arg(args, "path");
      return {
        icon: FolderTreeIcon,
        done: "Listed",
        doing: "Listing",
        target: !path || path === "." ? "repository root" : path,
        verb: "listed",
        noun: ["folder", "folders"],
      };
    }
    case "repo.list_modules":
      return {
        icon: PackageIcon,
        done: "Found the modules",
        doing: "Finding the modules",
        target: "",
        verb: "listed",
        noun: ["module list", "module lists"],
      };
    case "repo.search":
      return {
        icon: SearchIcon,
        done: "Searched for",
        doing: "Searching for",
        target: arg(args, "pattern") || arg(args, "query"),
        verb: "ran",
        noun: ["search", "searches"],
      };
    case "repo.write_file":
      return {
        icon: FilePenIcon,
        done: "Wrote",
        doing: "Writing",
        target: arg(args, "path"),
        verb: "wrote",
        noun: ["file", "files"],
      };
    case "repo.commit":
      return {
        icon: GitCommitHorizontalIcon,
        done: "Committed",
        doing: "Committing",
        target: oneLine(arg(args, "message")),
        verb: "made",
        noun: ["commit", "commits"],
      };
    case "github.openPR":
      return {
        icon: GitPullRequestIcon,
        done: "Opened a pull request",
        doing: "Opening a pull request",
        target: oneLine(arg(args, "title")),
        verb: "opened",
        noun: ["pull request", "pull requests"],
      };
    case "scan.lint": {
      const linters = (args as { linters?: unknown } | null)?.linters;
      const named = Array.isArray(linters) ? linters.filter((l) => typeof l === "string") : [];
      const path = arg(args, "path");
      return {
        icon: ScanSearchIcon,
        done: named.length > 0 ? `Linted with ${named.join(", ")}` : "Linted",
        doing: named.length > 0 ? `Linting with ${named.join(", ")}` : "Linting",
        target: !path || path === "." ? "the repository" : path,
        verb: "ran",
        noun: ["lint", "lints"],
      };
    }
    case "scan.secrets": {
      const path = arg(args, "path");
      return {
        icon: KeyRoundIcon,
        done: "Scanned for secrets in",
        doing: "Scanning for secrets in",
        target: !path || path === "." ? "the repository" : path,
        verb: "ran",
        noun: ["secret scan", "secret scans"],
      };
    }
    case "scan.dependencies": {
      const path = arg(args, "path");
      return {
        icon: ShieldAlertIcon,
        done: "Checked the dependencies of",
        doing: "Checking the dependencies of",
        target: !path || path === "." ? "the repository" : path,
        verb: "ran",
        noun: ["dependency scan", "dependency scans"],
      };
    }
    default:
      return {
        icon: WrenchIcon,
        done: `Called ${name}`,
        doing: `Calling ${name}`,
        target: oneLine(firstString(args)),
        verb: "called",
        noun: [name, name],
      };
  }
}

/** One line for a group of tool calls: "Read 9 files, listed 2 folders, ran 1 search". */
export function summarizeTools(turns: ToolTurn[]): string {
  const parts = new Map<string, { verb: string; noun: [string, string]; count: number }>();
  for (const turn of turns) {
    const d = describeTool(turn.name, turn.arguments);
    const key = `${d.verb} ${d.noun[1]}`;
    const part = parts.get(key) ?? { verb: d.verb, noun: d.noun, count: 0 };
    part.count += 1;
    parts.set(key, part);
  }
  const text = [...parts.values()]
    .map((p) => `${p.verb} ${p.count} ${p.count === 1 ? p.noun[0] : p.noun[1]}`)
    .join(", ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * What a call shows inline, without opening it: the error of a failed call, and what a call
 * that changes something wrote (a file's content, a commit message, a pull request). Reads,
 * listings and searches show nothing: they stay one line.
 */
export function toolPreview(turn: ToolTurn): string | null {
  if (turn.status === "failed") return turn.output?.trim() || null;
  switch (turn.name) {
    case "repo.write_file":
      return arg(turn.arguments, "content") || null;
    case "repo.commit":
      return arg(turn.arguments, "message") || null;
    case "github.openPR":
      return (
        [arg(turn.arguments, "title"), arg(turn.arguments, "body")].filter(Boolean).join("\n\n") ||
        null
      );
    default:
      return null;
  }
}
