---
name: open-pr
description: Open a pull request from the current branch to main the way this repo requires — CHANGELOG.md entry under [Unreleased], labels, the roadmap phase issue linked, every CI check watched until it finishes — and stop before merging (a human squash-merges). Use this whenever the user wants to open, create, submit, raise or ship a PR, push a branch for review, "get this merged", or asks whether a PR is ready to merge, even if they don't say "open-pr".
---

# Open a pull request

The rules for `main` (enforced on GitHub by `scripts/setup_repo_rules.py`, so they are not optional):

- Every change reaches `main` through a PR, **squash-merged**. No direct pushes, no merge or rebase merges.
- A PR merges only when **every** required check has run and passed (all jobs of `ci.yml` and `pr-checks.yml`) on a branch up to date with `main`.
- Every PR adds a **`CHANGELOG.md` entry under `[Unreleased]`**. There is no skip label.
- **You never merge.** No `gh pr merge`, no auto-merge. A human clicks "Squash and merge".

The squash commit takes the PR title and body, so they are the commit message on `main`.

## 1. Check the branch

```bash
git branch --show-current          # must not be main
git status --short                 # commit or ask about anything left
git fetch origin main
git log --oneline origin/main..HEAD
```

If you are on `main`, stop and offer to move the work to a new branch. If `origin/main` has moved, rebase onto it (`git rebase origin/main`) so the required "up to date" rule is met. Ask before rebasing a branch that is already pushed and shared.

## 2. CHANGELOG.md

```bash
git diff origin/main...HEAD -- CHANGELOG.md
```

If the branch adds nothing there, write the entry now, under `## [Unreleased]`, following the file's own rules: headings `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`; one line (or one bullet with sub-bullets for a phase) per change; match the tone and detail of the entries around it. Leave the PR link for step 5, once the number exists. Show the user the entry before committing it. Commit it with the work, before the push in step 4: CI only checks for an entry, it cannot write one.

## 3. Roadmap phase

If the branch touches a `specs/<date>-<slug>/` folder whose `requirements.md` has `Roadmap phase: <n>`:

- **Implemented:** do **not** mark the phase done yourself (no `complete-phase` here). Once the PR is open, the `Roadmap phase marked done` job of `pr-checks.yml` commits the mark to the branch. Doing it locally as well races that commit and the push is rejected. Step 5 picks up the bot's commit.
- **Planning only** (spec files, no code): label the PR `skip-roadmap` and `type:plan`.

Find the phase's issue so the PR closes it on merge:

```bash
gh issue list --label roadmap-phase --state open --search "<n> in:title" --json number,title
```

## 4. Push and open

```bash
git push -u origin HEAD
gh pr create --base main \
  --title "<title>" --body-file <scratchpad>/pr-body.md \
  --label <type:...> [--label area:...] [--label milestone:<m>] [--milestone "Milestone <m>: <name>"]
```

- **Title:** short and specific, in the style of `git log --oneline origin/main` (e.g. `Plan/2.6 start, approve and rerun`). It becomes the commit title on `main`.
- **Body:** fill `.github/pull_request_template.md` (Summary, Test plan, Checklist). Add `Closes #<issue>` for the phase issue. End with the attribution line from the system reminder, if any.
- **Labels:** one `type:` (`feature`, `fix`, `plan`, `chore`, `docs`); `area:` labels for what it touches (`engine`, `api`, `web`, `sandbox`, `ci`); `milestone:<m>` and the milestone when it implements a phase. If a label is missing, `python scripts/sync_roadmap_board.py` creates them.

## 5. Finish the branch

The bot's roadmap commit is pushed with the default token, so it does not rerun CI: the PR's head would have no CI run and could not merge. One more push of yours fixes that, and it must come **after** the bot's commit, never next to it:

1. If step 3 applies, wait for the `Roadmap phase marked done` check to finish (`gh pr checks <n> --watch`, or poll until it is not pending), then take its commit: `git pull --ff-only`. Never rebase or amend over it, and never force-push.
2. Add the PR link to the changelog entry (`([#<n>](<pr-url>))`, where `<pr-url>` is the PR's own URL from `gh pr view --json url -q .url`), commit, and push. This push reruns every check on the final head.

If a push is still rejected, `git pull --ff-only` and push again; do not amend a pushed commit.

## 6. Watch the checks

```bash
gh pr checks --watch --fail-fast
```

If a check fails, read its log (`gh run view <run-id> --log-failed`), fix the cause on the branch, push, and watch again. Do not rerun a failing job hoping it passes unless the log shows a flaky cause outside the change, and say so if you do.

## 7. Report

Tell the user the PR URL, its title, labels, and the status of every check. When all are green, say it is ready and that **they** squash-merge it on GitHub. Do not merge it yourself, even if asked to "ship" it: offer the link instead, and only proceed past this rule if the user explicitly overrides it for this PR.
