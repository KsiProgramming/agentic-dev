import type {
  Branch,
  Iteration,
  MapItem,
  MessageTurn,
  OrchestratorTask,
  Step,
  StepStatus,
  TaskStatus,
} from "../timeline";
import { isFindingsReport, SEVERITIES, type FindingsReport } from "../findings/findings";
import { itemName } from "./item-name";
import { describeTool } from "./tool-describe";

/**
 * The run's steps as the console's step list shows them: one row per step in run order, map
 * items, parallel branches, loop iterations, a router's route and an orchestrator's tasks nested
 * under their node. A scope (item, branch, iteration) that holds one step is that step's row,
 * named by the scope; one that holds several is a heading row with its steps under it. A task is
 * always a heading (its own status can differ from its worker's: a merge conflict, 6.3), and an
 * orchestrator that replanned has a heading per round.
 */
export type StepEntry = StepRow | ScopeRow;

export interface StepRow {
  kind: "step";
  /** Unique in the run, stable while it grows, and readable in a link: the node id with its
   * scope (`document[2]/writer`, `revise#2/reviewer`, `checks:lint/scan`,
   * `report_path>fix_first/fix_first_report`, `fix.b2/fixer` for an orchestrator's task, whose
   * id is unique across rounds). */
  key: string;
  step: Step;
  /** The node id, or the name of the scope the step is alone in. */
  name: string;
  /** A map item's kind, shown beside its name. */
  itemKind: string | null;
  depth: number;
  /** The map item, branch and iteration the step runs in (the innermost of each). */
  item: MapItem | null;
  branch: Branch | null;
  iteration: Iteration | null;
  /** The orchestrator task the step runs for. */
  task: OrchestratorTask | null;
}

export interface ScopeRow {
  kind: "scope";
  key: string;
  name: string;
  /** Shown beside the name as text: a map item's kind, a task's title, a round's cause. */
  itemKind: string | null;
  depth: number;
  status: TaskStatus;
  startedAt: string | null;
  endedAt: string | null;
  /** One line under the heading: why a task failed, or that it was dropped. */
  note?: string | null;
}

interface Scope {
  prefix: string;
  depth: number;
  item: MapItem | null;
  branch: Branch | null;
  iteration: Iteration | null;
  task: OrchestratorTask | null;
}

function keyOf(scope: Scope, nodeId: string): string {
  return scope.prefix ? `${scope.prefix}/${nodeId}` : nodeId;
}

/** A scope's steps: alone, the step is the scope's row; else a heading, then the steps. */
function visitScope(
  steps: Step[],
  scope: Scope,
  heading: Omit<ScopeRow, "kind" | "key" | "depth">,
  out: StepEntry[],
) {
  const [only] = steps;
  if (steps.length === 1 && only) {
    visit(only, scope, out, { name: heading.name, itemKind: heading.itemKind });
    return;
  }
  out.push({ kind: "scope", key: scope.prefix, depth: scope.depth, ...heading });
  for (const step of steps) visit(step, { ...scope, depth: scope.depth + 1 }, out);
}

function visit(
  step: Step,
  scope: Scope,
  out: StepEntry[],
  named?: { name: string; itemKind: string | null },
) {
  const key = keyOf(scope, step.id);
  out.push({
    kind: "step",
    key,
    step,
    name: named?.name ?? step.id,
    itemKind: named?.itemKind ?? null,
    depth: scope.depth,
    item: scope.item,
    branch: scope.branch,
    iteration: scope.iteration,
    task: scope.task,
  });
  const inner = { ...scope, depth: scope.depth + 1 };
  if (step.orchestrator) visitTasks(step, key, inner, out);
  for (const item of step.items ?? []) {
    const { name, kind } = itemName(item.item, item.index);
    visitScope(
      item.steps,
      { ...inner, prefix: `${key}[${item.index}]`, item },
      {
        name,
        itemKind: kind,
        status: item.status,
        startedAt: item.startedAt,
        endedAt: item.endedAt,
      },
      out,
    );
  }
  for (const branch of step.branches ?? []) {
    visitScope(
      branch.steps,
      { ...inner, prefix: `${key}:${branch.id}`, branch },
      {
        name: branch.id,
        itemKind: null,
        status: branch.status,
        startedAt: branch.startedAt,
        endedAt: branch.endedAt,
      },
      out,
    );
  }
  // A router's route: its steps under it, by their own names (a route is one node).
  for (const routed of step.router?.steps ?? []) {
    visit(routed, { ...inner, prefix: `${key}>${step.router?.chosen ?? "route"}` }, out);
  }
  for (const iteration of step.iterations ?? []) {
    const last = iteration.steps.at(-1);
    visitScope(
      iteration.steps,
      { ...inner, prefix: `${key}#${iteration.index}`, iteration },
      {
        name: `Iteration ${iteration.index}`,
        itemKind: null,
        status: last?.status ?? "running",
        startedAt: iteration.steps[0]?.startedAt ?? null,
        endedAt: last?.endedAt ?? null,
      },
      out,
    );
  }
}

/** The status of a group of tasks, for a round's heading: running while any is still to end,
 * else failed when one failed, else done. */
function roundStatus(tasks: OrchestratorTask[]): StepStatus {
  if (tasks.some((t) => t.status === "running" || t.status === "pending")) return "running";
  if (tasks.some((t) => t.status === "failed")) return "failed";
  if (tasks.some((t) => t.status === "cancelled")) return "cancelled";
  return "completed";
}

/** An orchestrator's tasks, each a heading over its worker's steps (key `<orchestrator>.<task>`),
 * under a heading per round once it replanned. */
function visitTasks(step: Step, key: string, inner: Scope, out: StepEntry[]) {
  const { rounds, tasks } = step.orchestrator!;
  const byRound = rounds.length > 1;
  for (const round of byRound ? rounds : [null]) {
    const mine = round ? tasks.filter((t) => t.round === round.round) : tasks;
    let depth = inner.depth;
    if (round) {
      const failures = round.replan ? round.replan.failed.length : 0;
      out.push({
        kind: "scope",
        key: `${key}~round-${round.round}`,
        name: `Round ${round.round}`,
        itemKind: round.replan
          ? `replanned after ${count(failures, "failure")}`
          : round.round === 1
            ? "first plan"
            : null,
        depth,
        status: roundStatus(mine),
        startedAt: mine[0]?.startedAt ?? null,
        endedAt: mine.at(-1)?.endedAt ?? null,
      });
      depth += 1;
    }
    for (const task of mine) {
      const prefix = `${key}.${task.id}`;
      out.push({
        kind: "scope",
        key: prefix,
        name: task.id,
        itemKind: task.title,
        depth,
        status: task.status,
        startedAt: task.startedAt,
        endedAt: task.endedAt,
        note:
          task.status === "dropped"
            ? "Dropped: the round stopped before it started"
            : task.status === "failed" && task.error
              ? firstLine(task.error)
              : null,
      });
      const scope: Scope = { ...inner, prefix, depth: depth + 1, task };
      for (const ran of task.steps) visit(ran, scope, out);
    }
  }
}

/** Every row of the step list, in run order. */
export function stepEntries(steps: Step[]): StepEntry[] {
  const out: StepEntry[] = [];
  const root: Scope = {
    prefix: "",
    depth: 0,
    item: null,
    branch: null,
    iteration: null,
    task: null,
  };
  for (const step of steps) visit(step, root, out);
  return out;
}

export function stepRows(entries: StepEntry[]): StepRow[] {
  return entries.filter((e): e is StepRow => e.kind === "step");
}

export function findEntry(entries: StepEntry[], key: string | null): StepRow | null {
  if (!key) return null;
  return stepRows(entries).find((e) => e.key === key) ?? null;
}

/** A map, a parallel, a loop, a router or an orchestrator: its children do the work. */
export function isContainer(step: Step): boolean {
  return (
    step.items !== null ||
    step.branches !== null ||
    step.iterations !== null ||
    step.router !== null ||
    step.orchestrator !== null
  );
}

/** The agent's answer: its last final message, or the text the step ends on. Text followed by
 * more work is a note, not an answer (`agentTurns`). */
export function lastMessage(step: Step): MessageTurn | null {
  for (let i = step.turns.length - 1; i >= 0; i--) {
    const turn = step.turns[i]!;
    if (turn.kind === "message" && (turn.final || i === step.turns.length - 1)) return turn;
  }
  return null;
}

function lastOf(rows: StepRow[], test: (row: StepRow) => boolean): StepRow | null {
  for (let i = rows.length - 1; i >= 0; i--) if (test(rows[i]!)) return rows[i]!;
  return null;
}

/** The step a failed run failed at: the deepest failed step, the last one if several. */
export function failingEntry(entries: StepEntry[]): StepRow | null {
  const rows = stepRows(entries);
  return (
    lastOf(rows, (r) => r.step.status === "failed" && !isContainer(r.step)) ??
    lastOf(rows, (r) => r.step.status === "failed")
  );
}

/**
 * The step the console shows when the URL names none: while live, the running step (the latest
 * one doing work); else the gate the run waits at, the step it failed at, or the last agent's
 * answer. So a finished run opens on what its agent produced.
 */
export function defaultEntry(entries: StepEntry[], live: boolean): StepRow | null {
  const rows = stepRows(entries);
  if (rows.length === 0) return null;
  if (live) {
    const running =
      lastOf(rows, (r) => r.step.status === "running" && !isContainer(r.step)) ??
      lastOf(rows, (r) => r.step.status === "running");
    if (running) return running;
  }
  return (
    rows.find((r) => r.step.status === "waiting") ??
    failingEntry(entries) ??
    lastOf(rows, (r) => lastMessage(r.step) !== null) ??
    rows.at(-1) ??
    null
  );
}

function firstLine(text: string, max = 120): string {
  const line =
    text
      .split("\n")
      .map((l) => l.replace(/^#+\s*/, "").trim())
      .find((l) => l.length > 0) ?? "";
  return line.length > max ? `${line.slice(0, max - 1)}…` : line;
}

function count(n: number, word: string, plural = `${word}s`): string {
  return `${n} ${n === 1 ? word : plural}`;
}

const SCANNED: Record<FindingsReport["scanner"], string> = {
  lint: "Linted",
  secrets: "Scanned for secrets",
  dependencies: "Checked dependencies",
  agent: "Reviewed",
  merged: "Merged",
};

/** A findings report in `text`, as a scan tool returns it or an agent answers with it (one
 * fenced block allowed); `null` when it is not one. */
function findingsIn(text: string | null): FindingsReport | null {
  const body = text
    ?.trim()
    .replace(/^```(?:json)?\s*/, "")
    .replace(/\s*```$/, "");
  if (!body?.startsWith("{")) return null;
  try {
    const value: unknown = JSON.parse(body);
    return isFindingsReport(value) ? value : null;
  } catch {
    return null;
  }
}

/** What a scan or a review found, so two scans read differently: "Linted 6 modules · 2
 * findings", "Scanned for secrets · no findings", "Skipped 6 modules: dotnet is not supported". */
function findingsLine(report: FindingsReport, agent: boolean): string {
  const total = SEVERITIES.reduce((sum, s) => sum + (report.counts[s] ?? 0), 0);
  const found = total === 0 ? "no findings" : count(total, "finding");
  if (agent) return total === 0 ? "Answered: no findings" : `Answered with ${found}`;
  const ran = report.checks.filter((c) => c.status === "ran").length;
  const skipped = report.checks.filter((c) => c.status !== "ran");
  if (ran === 0 && skipped.length > 0) {
    const reason = skipped[0]!.reason;
    return `Skipped ${count(skipped.length, "module")}${reason ? `: ${reason}` : ""}`;
  }
  const where = ran > 1 ? ` ${count(ran, "module")}` : "";
  const rest = skipped.length > 0 ? ` · ${skipped.length} skipped` : "";
  return `${SCANNED[report.scanner]}${where} · ${found}${rest}`;
}

/** Whether `text` is a JSON answer (an agent with an output schema), not prose. */
function isJson(text: string): boolean {
  return /^(?:```(?:json)?\s*)?[{[]/.test(text.trim());
}

/** How far an orchestrator got: "Planning", "2 of 4 tasks · round 2", then at the end "3 of 6
 * tasks · 2 rounds · merged 3 into agent/…/fix". */
export function orchestratorOutline(step: Step): string | null {
  const { rounds, tasks } = step.orchestrator!;
  const live = step.status === "running";
  const planned = rounds.some((r) => r.taskIds.length > 0) || tasks.length > 0;
  if (!planned) {
    if (live) return "Planning";
    return rounds.length > 0 ? "Planned no task" : null;
  }
  const done = tasks.filter((t) => t.status === "completed").length;
  const failed = tasks.filter((t) => t.status === "failed").length;
  const parts = [`${done} of ${count(tasks.length, "task")}`];
  if (failed > 0) parts.push(`${failed} failed`);
  if (rounds.length > 1) parts.push(live ? `round ${rounds.length}` : `${rounds.length} rounds`);
  const integration = rounds.findLast((r) => r.integration)?.integration;
  if (!live && integration && integration.merged.length > 0) {
    parts.push(`merged ${integration.merged.length} into ${integration.branch}`);
  }
  return parts.join(" · ");
}

/** One line on what a step did, for its row: the agent's answer, the tool's call, the gate's
 * decision, or how far a container got. Plain text: it comes from agent and repo content. */
export function stepOutline(step: Step): string | null {
  if (step.error && step.status === "failed") return firstLine(step.error);
  if (step.gate) {
    if (step.gate.decision === "approve") {
      const edits = step.gate.edits.length;
      return edits > 0 ? `Approved with edits to ${count(edits, "file")}` : "Approved";
    }
    if (step.gate.decision === "reject") return "Rejected";
    return step.status === "waiting" ? "Waiting for approval" : step.gate.title;
  }
  if (step.items) {
    const done = step.items.filter((i) => i.status === "completed").length;
    const failed = step.items.filter((i) => i.status === "failed").length;
    const total = step.itemCount ?? step.items.length;
    return `${done} of ${count(total, "item")}${failed ? ` · ${failed} failed` : ""}`;
  }
  if (step.branches) {
    const done = step.branches.filter((b) => b.status === "completed").length;
    return `${done} of ${count(step.branches.length, "branch", "branches")}`;
  }
  if (step.iterations) return count(step.iterations.length, "iteration");
  if (step.orchestrator) return orchestratorOutline(step);
  if (step.router) {
    if (step.router.chosen) return `Routed to ${step.router.chosen}`;
    return step.status === "running" ? "Choosing a route" : null;
  }
  if (step.merged) {
    const { sources, findingsIn, findingsOut } = step.merged;
    return `Merged ${count(findingsIn, "finding")} into ${findingsOut} from ${count(sources, "source")}`;
  }
  if (step.prUrl) return `Opened pull request #${step.prUrl.split("/").at(-1)}`;
  if (step.createdRepo) return `Created ${step.createdRepo.fullName}`;
  const message = lastMessage(step);
  const tool = step.turns.findLast((t) => t.kind === "tool");
  // A scan's or a review's result says what it found, not the call it made or the JSON's "{".
  const report = findingsIn(message?.text ?? null) ?? findingsIn(tool?.output ?? null);
  if (report) return findingsLine(report, message !== null && findingsIn(message.text) !== null);
  if (message && message.text.trim()) {
    return isJson(message.text) ? "Answered in JSON" : firstLine(message.text);
  }
  if (tool) {
    const d = describeTool(tool.name, tool.arguments);
    return d.target ? `${d.done} ${d.target}` : d.done;
  }
  return null;
}
