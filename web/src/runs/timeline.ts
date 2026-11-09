import { parseArtifact, parseArtifacts, type ArtifactVersion } from "./artifacts/artifacts";
import { addUsage, usageOfEvent, type TokenUsage } from "./cost";
import { parseChanges, parseEdits, type FileChange, type FileEdit } from "./gates";
import type { SpecParent } from "./spec-parents";
import type { RunEvent } from "./types";

export type { TokenUsage } from "./cost";

/**
 * The run as a story: one step per node in run order, map items, parallel branches, loop
 * iterations and a router's route nested inside their node, and inside each step its turns. Streamed `text_delta` chunks are merged into
 * one growing message per agent turn, and `reasoning_delta` chunks into one reasoning turn; a tool
 * call and its result form one tool turn. Payloads are data: nothing here is ever rendered as HTML.
 */

export type StepStatus = "running" | "waiting" | "completed" | "failed" | "cancelled";

export interface MessageTurn {
  kind: "message";
  /** The `seq` of the event that opened the turn: a stable React key. */
  key: number;
  /** The chunks joined in order, or the final `message` text once it arrived. */
  text: string;
  /** The `message` event replaced the merged chunks: the turn will not grow any more. */
  final: boolean;
  /** How many `text_delta` events the turn merged. */
  chunks: number;
}

export interface ToolTurn {
  kind: "tool";
  key: number;
  callId: string;
  name: string;
  arguments: unknown;
  /** Why the agent made the call: the tool's optional `description` argument, as plain text. */
  intent: string | null;
  /** The tool's output, once its result arrived. */
  output: string | null;
  status: "running" | "completed" | "failed";
  startedAt: string;
  endedAt: string | null;
}

/** The model's reasoning (Claude's summarized thinking), merged from `reasoning_delta` chunks. */
export interface ReasoningTurn {
  kind: "reasoning";
  key: number;
  text: string;
  startedAt: string;
}

export type Turn = MessageTurn | ToolTurn | ReasoningTurn;

export interface GateInfo {
  title: string;
  decision: string | null;
  comment: string | null;
  /** The files the writers before the gate changed, as it showed them. */
  changes: FileChange[];
  /** The approver's edits to them, once decided. */
  edits: FileEdit[];
}

export interface Step {
  /** The node id. */
  id: string;
  status: StepStatus;
  startedAt: string;
  endedAt: string | null;
  error: string | null;
  turns: Turn[];
  /** The node's own usage; `stepUsage` adds its map items, branches and iterations. */
  usage: TokenUsage | null;
  gate: GateInfo | null;
  prUrl: string | null;
  /** The repo the node created for the run (`github.createRepo`). */
  createdRepo: CreatedRepo | null;
  /** Set for a loop node: one entry per iteration, each with its own steps. */
  iterations: Iteration[] | null;
  /** Set for a map node: one entry per item, each with its own steps. */
  items: MapItem[] | null;
  /** How many items a map node has, once it started. */
  itemCount: number | null;
  /** Set for a parallel node: one entry per branch, each with its own steps. */
  branches: Branch[] | null;
  /** Why a loop stopped: `condition` or `max_iterations`. */
  stopReason: string | null;
  /** The typed port that failed the step (4.2): its `node_failed`'s `port`. */
  port: PortFailure | null;
  /** The run artifacts the step wrote (4.3), from its `artifact_written` events. */
  artifactsWritten: ArtifactVersion[];
  /** The versions of run artifacts the step read, from its `node_started`'s `reads`. */
  artifactsRead: ArtifactVersion[];
  /** What a `dedupe` or `vote` reduce merged (4.5): its `node_completed`'s `merged`. */
  merged: MergeCounts | null;
  /** Set for a router node (4.6): its routes, the one it took and why, and that route's steps. */
  router: RouterInfo | null;
  /** Set for an orchestrator node (6.4): its plans by round and its tasks, each with its steps. */
  orchestrator: OrchestratorInfo | null;
  /** Set for a subflow node (6.5): the workflow it calls and that workflow's steps. */
  subflow: SubflowInfo | null;
}

/** The stored workflow version a subflow calls (6.5), from its `node_started`. */
export interface CalledWorkflow {
  id: string;
  version: number;
  name: string;
}

export interface SubflowInfo {
  workflow: CalledWorkflow;
  /** The steps of the called workflow, under the ids they ran as. */
  steps: Step[];
}

/** A task's status: `pending` once planned and before it starts, `dropped` when a replan round
 * stopped before it started (6.2). A task that conflicted at integration (6.3) is `failed`. */
export type TaskStatus = StepStatus | "pending" | "dropped";

export interface OrchestratorTask {
  /** Its index across every round, the `item` its worker's events carry. */
  index: number;
  /** The task id the hub gave it: unique across rounds, its writer key's suffix. */
  id: string;
  /** The hub's title for it: model output, shown as text. */
  title: string;
  round: number;
  status: TaskStatus;
  startedAt: string | null;
  endedAt: string | null;
  error: string | null;
  /** The paths it conflicted on when its branch was merged, else `null`. */
  conflict: string[] | null;
  steps: Step[];
}

export interface Integration {
  branch: string;
  head: string | null;
  merged: string[];
  empty: string[];
  conflicts: { id: string; paths: string[] }[];
}

export interface PlanRound {
  /** 1 for the first plan. */
  round: number;
  /** The tasks planned, in plan order; empty until its `plan_made`. */
  taskIds: string[];
  /** Why the hub planned so (`plan_made`'s `reason`): model output, shown as text. */
  reason: string | null;
  /** For a replan: what the round before ended with (`replan_started`). */
  replan: { failed: { id: string; error: string }[]; dropped: string[] } | null;
  /** The integration branch after this round (`branch_integrated`), when the body writes. */
  integration: Integration | null;
}

export interface OrchestratorInfo {
  /** The most tasks the hub may plan (`node_started`'s `max_workers`). */
  maxWorkers: number | null;
  rounds: PlanRound[];
  /** Every task planned, in index order. */
  tasks: OrchestratorTask[];
}

export interface RouterInfo {
  /** The route ids it could take, `default` last when it has one (its `node_started`). */
  routes: string[];
  mode: "rule" | "classifier";
  /** The route it took (`route_chosen`), or `null` while it chooses or if it could not. */
  chosen: string | null;
  /** Why: the condition that held, `no route matched`, or the classifier's reason. */
  reason: string | null;
  /** The steps of the route it took. */
  steps: Step[];
}

export interface MergeCounts {
  sources: number;
  findingsIn: number;
  findingsOut: number;
}

/** A value that did not match a node's input or output schema, and where it went wrong. */
export interface PortFailure {
  side: "input" | "output";
  /** The node the value came from, on the input side, when it is the previous step. */
  fromNodeId: string | null;
  /** JSON pointers (empty for the value itself) and messages, the most relevant first. */
  errors: { pointer: string; message: string }[];
}

export interface CreatedRepo {
  fullName: string;
  url: string;
}

export interface Iteration {
  index: number;
  steps: Step[];
  /** The `until` condition's result after this iteration, once evaluated. */
  conditionMet: boolean | null;
}

export interface MapItem {
  index: number;
  item: unknown;
  status: StepStatus;
  startedAt: string;
  endedAt: string | null;
  error: string | null;
  steps: Step[];
}

export interface Branch {
  index: number;
  /** The id of the branch's node. */
  id: string;
  /** `cancelled` once the parallel's join was decided without it. */
  status: StepStatus;
  startedAt: string;
  endedAt: string | null;
  error: string | null;
  steps: Step[];
}

export interface Timeline {
  steps: Step[];
  workflowName: string | null;
  startedAt: string | null;
  endedAt: string | null;
  clock: RunClock;
  /** Why the run was cancelled (`run_cancelled`'s `reason`), and whether its gate expired. */
  cancelReason: string | null;
  expired: boolean;
}

/**
 * The run's active and waiting time, added up from its events the way the API does
 * (`agentic_store.sink.time_values`): active from `run_started` or `run_resumed` to
 * `gate_waiting` or the end, waiting from `gate_waiting` to `run_resumed` or the end. An
 * attempt that was cut off counts until its last event. The open stretch began at
 * `activeSince` or `waitingSince`; `clockAt` counts it up to now.
 */
export interface RunClock {
  /** `null` until the run started. */
  activeMs: number | null;
  waitingMs: number;
  activeSince: string | null;
  waitingSince: string | null;
}

const between = (from: string, to: string) => Math.max(0, Date.parse(to) - Date.parse(from));

/** The clock's totals with the open stretch counted up to `now`. */
export function clockAt(
  clock: RunClock,
  now: number,
): { activeMs: number | null; waitingMs: number } {
  const open = (since: string | null) => (since ? Math.max(0, now - Date.parse(since)) : 0);
  return {
    activeMs:
      clock.activeMs === null && !clock.activeSince
        ? null
        : (clock.activeMs ?? 0) + open(clock.activeSince),
    waitingMs: clock.waitingMs + open(clock.waitingSince),
  };
}

const END_STATUS: Record<string, StepStatus> = {
  node_completed: "completed",
  node_failed: "failed",
  node_cancelled: "cancelled",
};

const RUN_END: Record<string, StepStatus> = {
  run_completed: "completed",
  run_failed: "failed",
  run_cancelled: "cancelled",
};

function str(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function parsePort(value: unknown): PortFailure | null {
  if (typeof value !== "object" || value === null) return null;
  const port = value as Record<string, unknown>;
  if (port.side !== "input" && port.side !== "output") return null;
  const errors = Array.isArray(port.errors) ? (port.errors as unknown[]) : [];
  return {
    side: port.side,
    fromNodeId: str(port.from_node_id),
    errors: errors.flatMap((e) => {
      const error = (typeof e === "object" && e !== null ? e : {}) as Record<string, unknown>;
      const message = str(error.message);
      return message === null ? [] : [{ pointer: str(error.pointer) ?? "", message }];
    }),
  };
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function parseMerged(value: unknown): MergeCounts | null {
  if (typeof value !== "object" || value === null) return null;
  const merged = value as Record<string, unknown>;
  const [sources, findingsIn, findingsOut] = [
    num(merged.sources),
    num(merged.findings_in),
    num(merged.findings_out),
  ];
  if (sources === null || findingsIn === null || findingsOut === null) return null;
  return { sources, findingsIn, findingsOut };
}

function newStep(id: string, at: string): Step {
  return {
    id,
    status: "running",
    startedAt: at,
    endedAt: null,
    error: null,
    turns: [],
    usage: null,
    gate: null,
    prUrl: null,
    createdRepo: null,
    iterations: null,
    items: null,
    itemCount: null,
    branches: null,
    stopReason: null,
    port: null,
    artifactsWritten: [],
    artifactsRead: [],
    merged: null,
    router: null,
    orchestrator: null,
    subflow: null,
  };
}

/** The workflow a subflow's `node_started` names (6.5), if it names one. */
function calledWorkflow(value: unknown): CalledWorkflow | null {
  if (typeof value !== "object" || value === null) return null;
  const { id, version, name } = value as Record<string, unknown>;
  if (typeof id !== "string" || typeof version !== "number") return null;
  return { id, version, name: typeof name === "string" ? name : id };
}

/** A GitHub pull request URL; anything else (e.g. a `javascript:` URL) is not offered as a link. */
/** The repo a `repo_created` event names, if it is a GitHub repo (events are data). */
export function createdRepoOf(payload: Record<string, unknown>): CreatedRepo | null {
  const fullName = str(payload.full_name);
  const url = str(payload.url);
  if (fullName === null || url !== `https://github.com/${fullName}`) return null;
  return /^[^/\s]+\/[^/\s]+$/.test(fullName) ? { fullName, url } : null;
}

export function safePullRequestUrl(url: unknown): string | null {
  if (typeof url !== "string") return null;
  return /^https:\/\/github\.com\/[^/\s]+\/[^/\s]+\/pull\/\d+$/.test(url) ? url : null;
}

/** Where the events of one level go: the run's top level, a loop iteration, a map item, a
 * parallel branch or a router's route. */
interface Scope {
  steps: Step[];
}

class Builder {
  readonly timeline: Timeline = {
    steps: [],
    workflowName: null,
    startedAt: null,
    endedAt: null,
    clock: { activeMs: null, waitingMs: 0, activeSince: null, waitingSince: null },
    cancelReason: null,
    expired: false,
  };
  /** When the event before the current one was written. */
  private lastAt: string | null = null;
  /** The loops, maps, parallels and routers that have started and not ended yet, innermost
   * last. */
  private open: Step[] = [];
  private seen = new Set<number>();
  /** The `item` and `branch` tags each step's events carry: a router in a map runs once per
   * item, under the same id. */
  private tags = new WeakMap<Step, { item: number | null; branch: number | null }>();

  /** `parents`: each node's container from the run's spec (`specParents`), when it is known. */
  constructor(private readonly parents: ReadonlyMap<string, SpecParent> | null = null) {}

  add(event: RunEvent) {
    if (this.seen.has(event.seq)) return;
    this.seen.add(event.seq);
    const payload = event.payload ?? {};
    const at = event.created_at;
    this.tick(event.type, at, this.lastAt);
    this.lastAt = at;

    switch (event.type) {
      case "run_started":
        this.timeline.workflowName = str(payload.workflow_name);
        this.timeline.startedAt ??= at;
        return;
      case "run_completed":
      case "run_failed":
      case "run_cancelled":
        if (event.type === "run_cancelled") {
          this.timeline.cancelReason = str(payload.reason);
          this.timeline.expired = payload.expired === true;
        }
        this.timeline.endedAt = at;
        this.endUnfinished(RUN_END[event.type] ?? "cancelled", at);
        return;
    }

    const nodeId = event.node_id;
    if (!nodeId) return;
    const item = num(payload.item);
    const branch = num(payload.branch);

    // Events a loop, map or parallel writes about itself.
    switch (event.type) {
      case "loop_iteration_started": {
        const loop = this.container(nodeId, at, item, branch);
        loop.iterations ??= [];
        loop.iterations.push({
          index: num(payload.iteration) ?? loop.iterations.length + 1,
          steps: [],
          conditionMet: null,
        });
        return;
      }
      case "loop_condition_evaluated": {
        const loop = this.container(nodeId, at, item, branch);
        const iteration = loop.iterations?.at(-1);
        if (iteration && typeof payload.result === "boolean")
          iteration.conditionMet = payload.result;
        return;
      }
      case "map_item_started": {
        const map = this.container(nodeId, at, item, branch);
        map.items ??= [];
        const index = num(payload.index) ?? map.items.length;
        const existing = map.items.find((i) => i.index === index);
        if (existing) {
          existing.status = "running";
          existing.endedAt = null;
        } else {
          map.items.push({
            index,
            item: payload.item,
            status: "running",
            startedAt: at,
            endedAt: null,
            error: null,
            steps: [],
          });
          map.items.sort((a, b) => a.index - b.index);
        }
        return;
      }
      case "map_item_completed": {
        const map = this.container(nodeId, at, item, branch);
        const entry = map.items?.find((i) => i.index === num(payload.index));
        if (entry) {
          entry.status = (str(payload.status) as StepStatus | null) ?? "completed";
          entry.endedAt = at;
          entry.error = str(payload.error);
        }
        return;
      }
      case "parallel_branch_started": {
        const parallel = this.container(nodeId, at, item, branch);
        parallel.branches ??= [];
        const index = num(payload.index) ?? parallel.branches.length;
        const existing = parallel.branches.find((b) => b.index === index);
        if (existing) {
          existing.status = "running";
          existing.endedAt = null;
        } else {
          parallel.branches.push({
            index,
            id: str(payload.branch_id) ?? String(index),
            status: "running",
            startedAt: at,
            endedAt: null,
            error: null,
            steps: [],
          });
          parallel.branches.sort((a, b) => a.index - b.index);
        }
        return;
      }
      case "plan_made": {
        const info = this.orchestrator(nodeId, at, item, branch);
        const round = roundOf(info, num(payload.round) ?? info.rounds.length + 1);
        round.taskIds = [];
        round.reason = str(payload.reason);
        for (const task of records(payload.tasks)) {
          const id = str(task.id);
          if (id === null) continue;
          round.taskIds.push(id);
          if (info.tasks.some((t) => t.id === id)) continue;
          info.tasks.push({
            index: info.tasks.length,
            id,
            title: str(task.title) ?? id,
            round: round.round,
            status: "pending",
            startedAt: null,
            endedAt: null,
            error: null,
            conflict: null,
            steps: [],
          });
        }
        return;
      }
      case "task_started":
      case "task_completed": {
        const info = this.orchestrator(nodeId, at, item, branch);
        const task = taskOf(info, payload);
        if (event.type === "task_started") {
          task.status = "running";
          task.startedAt ??= at;
          task.endedAt = null;
          task.error = null;
        } else {
          const status = str(payload.status);
          task.status =
            status === "dropped" || status === "failed" || status === "cancelled"
              ? status
              : "completed";
          task.endedAt = at;
          task.error = str(payload.error);
        }
        return;
      }
      case "replan_started": {
        const info = this.orchestrator(nodeId, at, item, branch);
        const round = roundOf(info, num(payload.round) ?? info.rounds.length + 1);
        round.replan = {
          failed: records(payload.failed).flatMap((f) => {
            const id = str(f.id);
            return id === null ? [] : [{ id, error: str(f.error) ?? "" }];
          }),
          dropped: strings(payload.dropped),
        };
        return;
      }
      case "branch_integrated": {
        const info = this.orchestrator(nodeId, at, item, branch);
        const round = roundOf(info, num(payload.round) ?? Math.max(1, info.rounds.length));
        round.integration = {
          branch: str(payload.branch) ?? "",
          head: str(payload.head),
          merged: strings(payload.merged),
          empty: strings(payload.empty),
          conflicts: records(payload.conflicts).flatMap((c) => {
            const id = str(c.id);
            return id === null ? [] : [{ id, paths: strings(c.paths) }];
          }),
        };
        // The worker completed, but its branch did not merge: the task failed (6.3).
        for (const { id, paths } of round.integration.conflicts) {
          const task = info.tasks.find((t) => t.id === id);
          if (!task) continue;
          task.status = "failed";
          task.conflict = paths;
          task.error = conflictError(paths);
        }
        return;
      }
      case "parallel_branch_completed": {
        const parallel = this.container(nodeId, at, item, branch);
        const entry = parallel.branches?.find((b) => b.index === num(payload.index));
        if (entry) {
          entry.status = (str(payload.status) as StepStatus | null) ?? "completed";
          entry.endedAt = at;
          entry.error = str(payload.error);
        }
        return;
      }
    }

    const scope = this.scopeFor(nodeId, item, branch);
    let step = scope.steps.find((s) => s.id === nodeId);

    if (event.type === "node_started") {
      if (step) {
        // A node cut off by a worker restart runs again; a gate is announced again.
        step.status = "running";
        step.endedAt = null;
      } else {
        step = newStep(nodeId, at);
        scope.steps.push(step);
        this.tags.set(step, { item, branch });
      }
      if (payload.items !== undefined) {
        step.items ??= [];
        step.itemCount = num(payload.items);
      }
      if (payload.branches !== undefined) step.branches ??= [];
      if (payload.max_workers !== undefined) {
        // An orchestrator: its tasks run inside it. Resumed, it keeps the plans it made.
        step.orchestrator ??= { maxWorkers: null, rounds: [], tasks: [] };
        step.orchestrator.maxWorkers = num(payload.max_workers);
        if (!this.open.includes(step)) this.open.push(step);
      }
      if (Array.isArray(payload.routes)) {
        // A router: the route it takes runs inside it. Run again, it chooses afresh.
        step.router = {
          routes: payload.routes.filter((r): r is string => typeof r === "string"),
          mode: payload.mode === "classifier" ? "classifier" : "rule",
          chosen: null,
          reason: null,
          steps: [],
        };
        if (!this.open.includes(step)) this.open.push(step);
      }
      const called = calledWorkflow(payload.workflow);
      if (called) {
        // A subflow: the workflow it calls runs inside it. Resumed, it keeps its steps.
        step.subflow ??= { workflow: called, steps: [] };
        if (!this.open.includes(step)) this.open.push(step);
      }
      // A step run again reads (and writes) afresh.
      step.artifactsRead = parseArtifacts(payload.reads);
      step.artifactsWritten = [];
      return;
    }

    step ??= (() => {
      const created = newStep(nodeId, at);
      scope.steps.push(created);
      this.tags.set(created, { item, branch });
      return created;
    })();

    switch (event.type) {
      case "node_completed":
      case "node_failed":
      case "node_cancelled":
        step.status = END_STATUS[event.type] ?? "completed";
        step.endedAt = at;
        step.error = str(payload.error) ?? step.error;
        step.stopReason = str(payload.stop_reason);
        step.port = parsePort(payload.port);
        step.merged = parseMerged(payload.merged);
        if (step.router) step.router.chosen ??= str(payload.route);
        this.open = this.open.filter((s) => s !== step);
        return;
      case "route_chosen":
        if (step.router) {
          step.router.chosen = str(payload.route);
          step.router.reason = str(payload.reason);
        }
        return;
      case "gate_waiting":
        step.status = "waiting";
        step.gate = {
          title: str(payload.title) ?? "Approve?",
          decision: null,
          comment: null,
          changes: parseChanges(payload.changes),
          edits: [],
        };
        return;
      case "gate_decided":
        step.status = "running";
        step.gate = {
          title: step.gate?.title ?? "Approve?",
          decision: str(payload.decision),
          comment: str(payload.comment),
          changes: step.gate?.changes ?? [],
          edits: parseEdits(payload.edits),
        };
        return;
      case "pr_opened":
        step.prUrl = safePullRequestUrl(payload.url);
        return;
      case "repo_created":
        step.createdRepo = createdRepoOf(payload);
        return;
      case "artifact_written": {
        const written = parseArtifact({ ...payload, node_id: nodeId });
        if (written) step.artifactsWritten.push(written);
        return;
      }
      case "text_delta": {
        const last = step.turns.at(-1);
        const text = str(payload.text) ?? "";
        if (last?.kind === "message" && !last.final) {
          last.text += text;
          last.chunks += 1;
        } else {
          step.turns.push({ kind: "message", key: event.seq, text, final: false, chunks: 1 });
        }
        return;
      }
      case "reasoning_delta": {
        const last = step.turns.at(-1);
        const text = str(payload.text) ?? "";
        if (last?.kind === "reasoning") last.text += text;
        else step.turns.push({ kind: "reasoning", key: event.seq, text, startedAt: at });
        return;
      }
      case "message": {
        const last = step.turns.at(-1);
        const text = str(payload.text) ?? "";
        if (last?.kind === "message" && !last.final) {
          last.text = text;
          last.final = true;
        } else if (text) {
          step.turns.push({ kind: "message", key: event.seq, text, final: true, chunks: 0 });
        }
        return;
      }
      case "tool_call":
        step.turns.push({
          kind: "tool",
          key: event.seq,
          callId: str(payload.call_id) ?? String(event.seq),
          name: str(payload.name) ?? "tool",
          arguments: payload.arguments ?? {},
          intent: intentOf(payload.arguments),
          output: null,
          status: "running",
          startedAt: at,
          endedAt: null,
        });
        return;
      case "tool_result": {
        const callId = str(payload.call_id);
        const call = step.turns.findLast(
          (t): t is ToolTurn => t.kind === "tool" && t.callId === callId,
        );
        if (!call) return;
        call.output = str(payload.output) ?? "";
        call.status = payload.is_error === true ? "failed" : "completed";
        call.endedAt = at;
        return;
      }
      case "usage":
        step.usage = addUsage(step.usage, usageOfEvent(payload));
        return;
      case "failed":
        step.error = str(payload.error) ?? step.error;
        return;
    }
  }

  /** The loop, map or parallel `nodeId` whose events carry `item` and `branch`, opened if it
   * is not open yet. */
  private container(nodeId: string, at: string, item: number | null, branch: number | null): Step {
    const open = this.findOpen(nodeId, item);
    if (open) return open;
    const scope = this.scopeFor(nodeId, item, branch);
    let step = scope.steps.find((s) => s.id === nodeId);
    if (!step) {
      step = newStep(nodeId, at);
      scope.steps.push(step);
      this.tags.set(step, { item, branch });
    }
    this.open.push(step);
    return step;
  }

  /** The orchestrator `nodeId`'s plans and tasks, set up if its `node_started` did not. */
  private orchestrator(
    nodeId: string,
    at: string,
    item: number | null,
    branch: number | null,
  ): OrchestratorInfo {
    const step = this.container(nodeId, at, item, branch);
    step.orchestrator ??= { maxWorkers: null, rounds: [], tasks: [] };
    return step.orchestrator;
  }

  /** The innermost open container `nodeId` whose events carry `item` (any, without one). */
  private findOpen(nodeId: string, item: number | null): Step | undefined {
    return this.open.findLast(
      (s) => s.id === nodeId && (item === null || (this.tags.get(s)?.item ?? null) === item),
    );
  }

  /**
   * Where a node's events go. With the spec, into the branch, item, iteration or route its node
   * is in. Without it (or before that container started), events tagged with a map `item` go to
   * that item of the innermost open map, those tagged with a `branch` to that branch of the
   * innermost open parallel, those carrying the innermost open router's own tags to its route;
   * others go to the current iteration of the innermost open loop, or the top level.
   */
  private scopeFor(nodeId: string, item: number | null, branch: number | null): Scope {
    const parent = this.parents?.get(nodeId);
    const known = parent ? this.findOpen(parent.container, item) : undefined;
    if (parent && known) {
      const scope =
        parent.kind === "parallel"
          ? known.branches?.find((e) => e.index === parent.branch)
          : parent.kind === "map"
            ? known.items?.find((e) => e.index === item)
            : parent.kind === "loop"
              ? known.iterations?.at(-1)
              : parent.kind === "orchestrator"
                ? known.orchestrator?.tasks.find((t) => t.index === item)
                : parent.kind === "subflow"
                  ? known.subflow
                  : known.router;
      if (scope) return scope;
    }
    for (let i = this.open.length - 1; i >= 0; i--) {
      const container = this.open[i]!;
      if (container.id === nodeId) continue;
      if (container.router || container.subflow) {
        const tags = this.tags.get(container);
        if ((tags?.item ?? null) === item && (tags?.branch ?? null) === branch) {
          return container.router ?? container.subflow!;
        }
        continue;
      }
      if (item !== null && container.orchestrator) {
        const task = container.orchestrator.tasks.find((t) => t.index === item);
        if (task) return task;
        continue;
      }
      if (item !== null && container.items) {
        const entry = container.items.find((e) => e.index === item);
        if (entry) return entry;
        continue;
      }
      if (branch !== null && container.branches) {
        const entry = container.branches.find((e) => e.index === branch);
        if (entry) return entry;
        continue;
      }
      if (item === null && branch === null && container.iterations) {
        const iteration = container.iterations.at(-1);
        if (iteration) return iteration;
      }
    }
    return this.timeline;
  }

  /** Moves the run's clock (see `RunClock`). `before` is the time of the previous event. */
  private tick(type: string, at: string, before: string | null) {
    const clock = this.timeline.clock;
    const closeActive = (end: string | null) => {
      if (clock.activeSince && end)
        clock.activeMs = (clock.activeMs ?? 0) + between(clock.activeSince, end);
      clock.activeSince = null;
    };
    const closeWaiting = () => {
      if (clock.waitingSince) clock.waitingMs += between(clock.waitingSince, at);
      clock.waitingSince = null;
    };
    if (type === "run_started" || type === "run_resumed") {
      closeActive(before);
      closeWaiting();
      clock.activeMs ??= 0;
      clock.activeSince = at;
    } else if (type === "gate_waiting") {
      closeActive(at);
      clock.waitingSince ??= at;
    } else if (type in RUN_END) {
      closeActive(at);
      closeWaiting();
    }
  }

  /** The run ended: steps cut off without their own end take its status. */
  private endUnfinished(status: StepStatus, at: string) {
    const visit = (steps: Step[]) => {
      for (const step of steps) {
        if (step.status === "running" || step.status === "waiting") {
          step.status = status;
          step.endedAt ??= at;
        }
        for (const iteration of step.iterations ?? []) visit(iteration.steps);
        if (step.router) visit(step.router.steps);
        if (step.subflow) visit(step.subflow.steps);
        for (const task of step.orchestrator?.tasks ?? []) {
          if (task.status === "pending") task.status = "cancelled";
          else if (task.status === "running" || task.status === "waiting") {
            task.status = status;
            task.endedAt ??= at;
          }
          visit(task.steps);
        }
        for (const entry of [...(step.items ?? []), ...(step.branches ?? [])]) {
          if (entry.status === "running") {
            entry.status = status;
            entry.endedAt ??= at;
          }
          visit(entry.steps);
        }
      }
    };
    visit(this.timeline.steps);
    this.open = [];
  }
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

/** The objects in a payload's list (events are data: anything else is left out). */
function records(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (v): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v),
  );
}

/** Round `n` of an orchestrator's plans, added (with any rounds before it) if it is new. */
function roundOf(info: OrchestratorInfo, n: number): PlanRound {
  while (info.rounds.length < n) {
    info.rounds.push({
      round: info.rounds.length + 1,
      taskIds: [],
      reason: null,
      replan: null,
      integration: null,
    });
  }
  return info.rounds[n - 1]!;
}

/** The task a `task_started` or `task_completed` names, added if no `plan_made` listed it. */
function taskOf(info: OrchestratorInfo, payload: Record<string, unknown>): OrchestratorTask {
  const index = num(payload.index) ?? info.tasks.length;
  const id = str(payload.task_id) ?? String(index);
  let task = info.tasks.find((t) => t.index === index) ?? info.tasks.find((t) => t.id === id);
  if (!task) {
    task = {
      index,
      id,
      title: str(payload.title) ?? id,
      round: Math.max(1, info.rounds.length),
      status: "pending",
      startedAt: null,
      endedAt: null,
      error: null,
      conflict: null,
      steps: [],
    };
    info.tasks.push(task);
    info.tasks.sort((a, b) => a.index - b.index);
  }
  return task;
}

/** The engine's words for a task whose branch conflicted (`conflict_error`): ten paths, then
 * how many more. */
export function conflictError(paths: string[]): string {
  const shown = paths.slice(0, 10).join(", ");
  const more = paths.length > 10 ? ` and ${paths.length - 10} more` : "";
  return `conflicts with earlier tasks on ${shown}${more}`;
}

/** The call's `description` argument, trimmed to one line; `null` when there is none. */
function intentOf(args: unknown): string | null {
  if (typeof args !== "object" || args === null || Array.isArray(args)) return null;
  const description = (args as Record<string, unknown>).description;
  if (typeof description !== "string") return null;
  const line = description.replace(/\s+/g, " ").trim();
  return line || null;
}

/** The timeline of a run's events, given in `seq` order. Duplicate `seq`s are ignored. With
 * `parents` (from the run's spec, `specParents`), nested nodes are placed by their spec. */
export function buildTimeline(
  events: readonly RunEvent[],
  parents: ReadonlyMap<string, SpecParent> | null = null,
): Timeline {
  const builder = new Builder(parents);
  for (const event of events) builder.add(event);
  return builder.timeline;
}

/** One row of the Raw events tab: an event, or consecutive chunks of one message folded. */
export type RawRow<E extends RunEvent = RunEvent> =
  | { kind: "event"; event: E }
  | {
      kind: "text";
      /** What was streamed: the answer's text or the model's reasoning. */
      type: DeltaType;
      /** The chunks, in order. */
      events: [E, ...E[]];
      /** The chunks joined: the message as it was streamed. */
      text: string;
      nodeId: string | null;
      item: number | null;
    };

type DeltaType = "text_delta" | "reasoning_delta";

const isDelta = (type: string): type is DeltaType =>
  type === "text_delta" || type === "reasoning_delta";

/**
 * Fold consecutive `text_delta` (or `reasoning_delta`) events of the same node and map item into
 * one row, so a streamed message reads as one paragraph rather than one row per chunk. Any other
 * event, a chunk of the other kind, or a chunk of another node or item, ends the fold.
 */
export function foldDeltas<E extends RunEvent>(events: readonly E[]): RawRow<E>[] {
  const rows: RawRow<E>[] = [];
  for (const event of events) {
    const last = rows.at(-1);
    const type = event.type;
    if (!isDelta(type)) {
      rows.push({ kind: "event", event });
      continue;
    }
    const item = num(event.payload?.item);
    const text = str(event.payload?.text) ?? "";
    if (
      last?.kind === "text" &&
      last.type === type &&
      last.nodeId === (event.node_id ?? null) &&
      last.item === item
    ) {
      last.events.push(event);
      last.text += text;
    } else {
      rows.push({ kind: "text", type, events: [event], text, nodeId: event.node_id ?? null, item });
    }
  }
  return rows;
}

/** A step's usage with that of its map items, branches, loop iterations, route and tasks:
 * what the node cost. */
export function stepUsage(step: Step): TokenUsage | null {
  let total = step.usage;
  if (step.router) total = addUsage(total, stepsUsage(step.router.steps));
  if (step.subflow) total = addUsage(total, stepsUsage(step.subflow.steps));
  for (const item of step.items ?? []) total = addUsage(total, stepsUsage(item.steps));
  for (const branch of step.branches ?? []) total = addUsage(total, stepsUsage(branch.steps));
  for (const iteration of step.iterations ?? []) {
    total = addUsage(total, stepsUsage(iteration.steps));
  }
  for (const task of step.orchestrator?.tasks ?? []) {
    total = addUsage(total, stepsUsage(task.steps));
  }
  return total;
}

/** The usage of `steps` and everything nested in them; for the run, its timeline's steps. */
export function stepsUsage(steps: Step[]): TokenUsage | null {
  return steps.reduce<TokenUsage | null>((total, step) => addUsage(total, stepUsage(step)), null);
}
