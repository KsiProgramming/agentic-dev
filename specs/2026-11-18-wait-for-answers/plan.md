# Plan: A run that asks waits for the answer

Roadmap phase: 7.9. Work in this order; each group ends green (`uv run ruff check`, `uv run mypy`, `uv run pytest` per package, never `packages/sandbox/tests` whole).

## 1. Engine: the `wait_for` step
- `spec/models.py`: `WaitForNode` (`type: "wait_for"`, `id`, `title`, `on`, `ttl_s`), added to the node union, the node manifests (`nodes.py`), the validation passes that list `GateNode` (loop-body rules, `map`/`parallel` refusal, `ttl_s` at most the policy's, root-sequence rules) and the JSON Schema export.
- `gate.py` (or `wait.py`): `run_wait_node` interrupts with a request `{title, wait_for: {...}, ttl_s}`; resumed with `{decision: "approve", decided_by: "jira:comment"}`, it completes with `data {answered: true}`.
- `graph/compile.py` and `graph/run.py`: treat it as a step node; `_wait` emits `gate_waiting` with `wait_for` (its issue and `after_comment_id`, read from the result of `after_from`'s tool node); the `jira.comment` tool returns `comment_id`.
- Size: the same places as `GateNode` today (about 40 matches in 8 engine files). No new status.

## 2. Store and worker
- `approvals.py`: refuse a human decision on a `wait_for` (`409 not_a_gate`); add `answer_arrived(run_id, node_id)` (queue once, idempotent, audit `wait.answered`).
- `expiry.py`: expire a `wait_for` with `ANSWERS_EXPIRED_REASON`, audit `wait.expired`.
- `sink.py`: keep `waiting_gate` with `wait_for` so lists and the Inbox can read it.
- Worker: an answer sweep (`JIRA_ANSWER_SWEEP_S`) running the direct check for each waiting `wait_for`; a restart mid-wait resumes from the checkpoint and still waits (no change beyond tests).

## 3. Jira
- `agentic_jira`: `WEBHOOK_EVENTS` gains `jira:comment_created`; `parse_event` reads only ids (issue key, comment id, author `accountId`); `IssueComment.author_id`; `JiraPlatform.get_issue` unchanged; the fake gets comment events and an author id; existing webhooks are re-registered with the new event on their next renewal (a migration note, and a one-off refresh on start).
- `api/jira/webhooks.py`: a comment delivery is recorded and deduplicated, dropped for a not-picked project, else it triggers the same check as "Check now", which ignores the platform's own comments (footer, not account); then `answer_arrived` for each waiting run on that issue. It never starts a run.
- `api/runs`: `POST /runs/{id}/answers/check` (Check now): `get_issue`, count newer comments by others, resume if any; `409` if the run is not at a `wait_for`.

## 4. SDD template (`sdd.py`)
- `clarify` moves inside `spec_loop` after `approve_spec`; routes `ask` only on an approval with markers and fewer than `max_clarifications` rounds; its sequence is `questions`, `post_questions` (new prompt: the build does **not** go on; it waits for the answer), `ask_jira`, `wait_for_answers`; `build_on_assumptions` gate after the loop when markers remain; `SddParams.max_clarifications` and `answer_ttl_s`.
- `_SPEC_WRITER`: on a pass after a wait, read the issue's comments after the questions as the team's answers (data), apply them, remove or narrow the markers; keep `_REVISING` for revisions.
- Regenerate `tests/fixtures/specs/valid/sdd.json`, the JSON Schema and OpenAPI exports.

## 5. Console (web)
- `RunBanner` / waiting state: "Waiting for answers on KAN-5", `StatusBadge`, `WaitingTime`, `IdChip href` to the issue, "Check now" (`LoadingState`/error toast on failure). Inbox row without Approve. Tests at 375 and 1440 px, light and dark; axe check.

## 6. Docs and real run
- `docs/` (connecting Jira: the comment event and who answers), tech-stack and lessons are already in this branch; changelog completed with the build.
- A real Claude run (`AGENTIC_RUNTIME=claude`) on an issue with open questions, read step by step in the console; record anything wrong in `lessons.md`.
