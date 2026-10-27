---
name: plan-feature
description: Plan the next roadmap feature for this repo. Finds the next unplanned phase in specs/roadmap.md, creates a planning branch, interviews the user about the feature spec, then writes specs/YYYY-MM-DD-feature-name/ with plan.md, requirements.md and validation.md, guided by specs/mission.md and specs/tech-stack.md. Use this whenever the user wants to plan, spec out, scope or start the "next feature", "next phase" or "next roadmap item", or asks what to work on next and wants a plan written, even if they don't say "plan-feature".
---

# Plan the next roadmap feature

The goal is a small, reviewable planning package for one roadmap phase, written only after the user has shaped it. The specs in `specs/` are the source of truth for this project, so the plan must fit them rather than invent its own direction.

## 1. Load context

Read these in full before doing anything else:

- `specs/roadmap.md`: the ordered phases with their "Done when" checks.
- `specs/mission.md`: principles, v1 decisions and non-goals. Use them to keep scope honest (for example: gates before irreversible actions, repo content is data, small verifiable steps).
- `specs/tech-stack.md`: the chosen libraries, tools and policy limits. The plan should use these choices, not alternatives.

## 2. Find the next feature

Milestones are listed in the order they are worked, which is not always their number (Milestone 11 sits after Milestone 4). If the roadmap has a "**Next up: Milestone N**" line, the next feature is the **first phase of milestone N that has not been planned yet**; once all of milestone N is planned, or with no such line, it is the **first phase in the file that has not been planned yet**. A phase counts as planned when an existing `specs/YYYY-MM-DD-*/requirements.md` names it in its `Roadmap phase:` line. Check those folders, and also glance at `git branch -a` for `plan/<phase>-*` branches in case planning started elsewhere.

If an earlier phase is unplanned but a later one is planned, still pick the earliest one and mention the gap to the user. Note any phases the chosen one depends on that are not done yet, since that affects scope.

Tell the user in one or two lines which phase you picked (number, title, "Done when") and why.

## 3. Create the branch

Pick a short kebab-case slug from the phase title (3 to 5 words, e.g. `repo-scaffold`, `workflow-spec-v0`, `gate-primitive`). Then:

```bash
git status --porcelain        # if not clean, ask the user before switching
git switch main && git pull --ff-only   # skip the pull if there is no remote
git switch -c plan/<phase>-<slug>       # e.g. plan/0.1-repo-scaffold
```

Branching before any file is written keeps the planning work isolated and easy to review as a PR.

## 4. Interview the user (before writing anything)

Do not write any spec files until the user has answered. The interview is the point of the skill: the roadmap line is only a one-row summary, and the user owns the decisions that turn it into a real scope.

Make **one** `AskUserQuestion` call with **three questions**, one per output file. Draft the options yourself from the roadmap row, mission and tech stack so the user mostly picks rather than types; put your recommended option first and mark it "(Recommended)". Use `multiSelect` where choices are not exclusive.

1. **Requirements (scope)**: header like `Scope`. What is in and out of this phase: e.g. minimal slice that only meets "Done when" vs. slightly broader, which sub-parts to include, key open decisions (a library choice not fixed in the tech stack, an API shape, a data model detail).
2. **Plan (approach)**: header like `Approach`. How to build it: e.g. order of work (backend first, contract first, test first), how to split into task groups, how much tooling/scaffolding to add now vs. later.
3. **Validation (done)**: header like `Validation`. How we prove it works and can merge: e.g. which tests (unit, integration with Testcontainers, end-to-end), the demo for "Done when", CI checks that must be green, manual checks.

Make the options concrete for this specific phase, not generic. If the answers leave something important ambiguous, ask a short follow-up; otherwise proceed.

## 5. Write the planning package

Create `specs/<YYYY-MM-DD>-<slug>/` using today's date (`date +%F`). Write the three files below. Keep them short and concrete; a reviewer should read all three in a few minutes. Reflect the user's answers explicitly, and cite mission principles or tech-stack choices where they drive a decision.

### requirements.md

```markdown
# <Phase title>

Roadmap phase: <number>
Branch: plan/<phase>-<slug>

## Context
Why this phase now, what it depends on, and what it unblocks. Link the relevant mission principles and tech-stack choices.

## Scope
### In scope
- ...
### Out of scope
- ... (and which later phase covers it, if any)

## Decisions
| Decision | Choice | Rationale |
|---|---|---|

## Open questions
- ... (or "None")
```

### plan.md

A series of numbered task groups. Each group is a coherent chunk that could be one commit or small PR, ordered so the project stays working after each one. Under each group, list concrete tasks (files, modules, commands).

```markdown
# Plan: <Phase title>

## 1. <Group name>
- [ ] ...
- [ ] ...

## 2. <Group name>
- [ ] ...
```

### validation.md

How we know the implementation succeeded and can be merged. Start from the roadmap's "Done when" and make it checkable.

```markdown
# Validation: <Phase title>

## Done when (from roadmap)
> <copied text>

## Automated checks
- [ ] ... (test names or areas, lint, type check, CI job)

## Manual / demo checks
- [ ] ... (exact commands or steps and the expected result)

## Merge criteria
- [ ] All checks above pass in CI
- [ ] ... (docs updated, no secrets in logs, etc.)
```

## 6. Wrap up

Summarise for the user: the phase, the branch name, the folder path, and one line per file on what it contains. Do not commit unless the user asks; offer to commit the three files on the planning branch.
