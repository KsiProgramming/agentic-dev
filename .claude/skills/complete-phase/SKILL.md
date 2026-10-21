---
name: complete-phase
description: Mark the roadmap phase implemented on the current branch as completed in specs/roadmap.md, setting its Status to "✅ Done ([#<pr>](<pr-url>))" and committing the change. Use this when the user says a phase or feature is finished, wants to mark a roadmap phase done/completed, is about to open or merge the PR that implements a phase, or the "Roadmap phase marked done" CI check failed.
---

# Mark a roadmap phase as completed

`specs/roadmap.md` has a Status column per phase. The PR that implements a phase sets it to `✅ Done ([#<pr>](<pr-url>))`. The `Roadmap phase marked done` job in `.github/workflows/pr-checks.yml` does this automatically on same-repo PRs and fails the PR if it is still missing. This skill does the same thing locally, before pushing, so the branch is already correct.

All the logic lives in `scripts/check_roadmap.py`; use it rather than editing the table by hand, so the skill and CI always agree.

## 1. Find the phase

The phase is the one named by the `Roadmap phase: <number>` line in `requirements.md` of the spec folder (`specs/<date>-<slug>/`) this branch touches.

```bash
git fetch origin main
git diff --name-only origin/main...HEAD -- 'specs/*/requirements.md'
```

If no spec folder is touched, or the user named a different phase, ask which phase they mean before changing anything.

Check the phase really is implemented: read its "Done when" in `specs/roadmap.md` and the spec's `validation.md`, and tell the user if the branch looks like planning only (spec files but no code). A planning-only PR should not be marked done; it gets the `skip-roadmap` label instead.

## 2. Get the PR URL

```bash
gh pr view --json number,url
```

If there is no PR yet, ask the user whether to open one now (`gh pr create`) or to stop here. Without a PR there is no link to record; CI will mark the phase once the PR is opened.

## 3. Mark it done

```bash
python scripts/check_roadmap.py origin/main HEAD --mark-done <pr-url>
python scripts/check_roadmap.py origin/main HEAD    # must print "Roadmap marks phase(s) ... as done."
```

If the phase was already marked, the script says so and changes nothing.

## 4. Commit and report

```bash
git commit -m "Mark roadmap phase <number> done" -- specs/roadmap.md
```

Also make sure `CHANGELOG.md` has an `[Unreleased]` entry for the phase with the PR link (the changelog CI check requires one). Push only if the user asks. Tell the user the phase number, its new Status, and the commit.
