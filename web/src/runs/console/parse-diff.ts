/**
 * The text `repo.diff` returns (13.1, tech-stack → Tool layer) as a file list and hunks, so the
 * console draws it as a diff:
 *
 *     writer changed 2 files (+3 -1) against the run's base abc1234:
 *     modified src/a.py (+2 -1)
 *     added tests/t.py (+1 -0)
 *
 *     diff --git a/src/a.py b/src/a.py
 *     ...
 *     (truncated at 256 KB: call again with path to read one file)
 *
 * It is repo content: every line is shown as text, never as markup. Anything that does not have
 * this shape (an error, a refusal) parses to `null` and is shown as plain text.
 */

export type DiffStatus = "added" | "modified" | "deleted" | "renamed";

export interface DiffFileSummary {
  status: DiffStatus;
  path: string;
  oldPath: string | null;
  /** `null` for a binary file. */
  added: number | null;
  removed: number | null;
}

export type DiffLineKind = "added" | "removed" | "context" | "hunk" | "note";

export interface DiffLine {
  kind: DiffLineKind;
  /** The line without its `+`, `-` or space marker. */
  text: string;
  /** The line's number on the old and the new side, for the gutter; `null` where it has none. */
  oldLine: number | null;
  newLine: number | null;
}

export interface DiffSection {
  /** The file's path after the change. */
  path: string;
  lines: DiffLine[];
}

export interface ParsedDiff {
  /** "test_writer changed 2 files (+3 -1) against the run's base abc1234:" */
  summary: string;
  files: DiffFileSummary[];
  sections: DiffSection[];
  /** The note a cut diff ends with, if it was cut. */
  truncated: string | null;
}

const SUMMARY = /^\S+ changed \d+ files? \(\+\d+ -\d+\) against the run's base [0-9a-f]+:$/;
const FILE_LINE = /^(added|modified|deleted|renamed) (.+) \((\+\d+ -\d+|binary, not shown)\)$/;
const TRUNCATED = /^\(truncated at \d+ KB: call again with path to read one file\)$/;
const HUNK = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/;
// The headers git writes between `diff --git` and the first hunk.
const META =
  /^(index |new file mode|deleted file mode|old mode|new mode|similarity index|dissimilarity index|rename from|rename to|copy from|copy to|--- |\+\+\+ )/;

function parseFileLine(line: string): DiffFileSummary | null {
  const match = FILE_LINE.exec(line);
  if (!match) return null;
  const [, status, name, counts] = match;
  const [from, to] = name!.split(" -> ");
  const path = to ?? from!;
  const found = /^\+(\d+) -(\d+)$/.exec(counts!);
  return {
    status: status as DiffStatus,
    path,
    oldPath: to !== undefined ? from! : null,
    added: found ? Number(found[1]) : null,
    removed: found ? Number(found[2]) : null,
  };
}

/** The path a `diff --git a/<old> b/<new>` line names, the new side. */
function sectionPath(line: string, known: DiffFileSummary[]): string {
  const rest = line.slice("diff --git ".length);
  // Paths with spaces are ambiguous here: prefer one the file list names.
  const named = known.find((f) => rest.endsWith(` b/${f.path}`));
  if (named) return named.path;
  const at = rest.lastIndexOf(" b/");
  return at >= 0 ? rest.slice(at + 3) : rest;
}

export function parseRepoDiff(text: string): ParsedDiff | null {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const summary = lines[0] ?? "";
  if (!SUMMARY.test(summary)) return null;

  const files: DiffFileSummary[] = [];
  let i = 1;
  for (; i < lines.length; i++) {
    const file = parseFileLine(lines[i]!);
    if (!file) break;
    files.push(file);
  }
  if (files.length === 0) return null;

  const sections: DiffSection[] = [];
  let truncated: string | null = null;
  let section: DiffSection | null = null;
  let oldLine = 0;
  let newLine = 0;
  let inHunk = false;
  for (; i < lines.length; i++) {
    const line = lines[i]!;
    if (TRUNCATED.test(line)) {
      truncated = line.slice(1, -1);
      continue;
    }
    if (line.startsWith("diff --git ")) {
      section = { path: sectionPath(line, files), lines: [] };
      sections.push(section);
      inHunk = false;
      continue;
    }
    if (!section) continue;
    const hunk = HUNK.exec(line);
    if (hunk) {
      oldLine = Number(hunk[1]);
      newLine = Number(hunk[2]);
      inHunk = true;
      section.lines.push({ kind: "hunk", text: line, oldLine: null, newLine: null });
      continue;
    }
    if (!inHunk) {
      // A binary file has no hunk: git says so on one line.
      if (line.startsWith("Binary files ") || line.startsWith("GIT binary patch")) {
        section.lines.push({
          kind: "note",
          text: "Binary file, not shown",
          oldLine: null,
          newLine: null,
        });
      } else if (!META.test(line) && line !== "") {
        section.lines.push({ kind: "note", text: line, oldLine: null, newLine: null });
      }
      continue;
    }
    if (line.startsWith("\\")) {
      section.lines.push({ kind: "note", text: line.slice(2), oldLine: null, newLine: null });
    } else if (line.startsWith("+")) {
      section.lines.push({ kind: "added", text: line.slice(1), oldLine: null, newLine: newLine++ });
    } else if (line.startsWith("-")) {
      section.lines.push({
        kind: "removed",
        text: line.slice(1),
        oldLine: oldLine++,
        newLine: null,
      });
    } else if (line.startsWith(" ")) {
      section.lines.push({
        kind: "context",
        text: line.slice(1),
        oldLine: oldLine++,
        newLine: newLine++,
      });
    }
    // An empty line between a hunk's end and the next file is not part of the diff.
  }
  return { summary, files, sections, truncated };
}
