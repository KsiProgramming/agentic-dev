# Validation: Verify Copilot SDK terms for hosted multi-tenant use

## Done when (from roadmap)
> Go/no-go recorded in tech-stack decisions log

Made checkable: the decisions log holds a verdict for each deployment mode, every verdict links to evidence in `findings.md`, and the specs that mention Copilot agree with it.

## Automated checks
- [ ] CI's roadmap check (`scripts/check_roadmap.py`) passes, and the phase is marked done by CI or `complete-phase`.
- [ ] Markdown links in the changed specs resolve (the decisions-log row to `findings.md`, the findings' source URLs well-formed).
- [ ] `git grep -n -i "token\|secret\|api[_-]key"` over `specs/2026-11-18-copilot-sdk-terms/` finds no credential value.
- [ ] No changes under `packages/` or `web/`, so the existing lint, type and test jobs have nothing new to fail. They still run green.

## Manual / demo checks
- [ ] `tech-stack.md` decisions log has one row for self-hosted and one for hosted multi-tenant, each `go`, `conditional go` or `no-go`, with its conditions.
- [ ] Every claim in `findings.md` has a quoted clause, a URL and a date, or is marked "unclear".
- [ ] The spike's result is recorded (credential type, headless or not, custom tool worked or not, usage fields), or says "not run" with the reason, and the verdict is capped at `conditional go` in that case.
- [ ] The verdict says whether Copilot may run on a person's own OAuth token from the platform, and that it never uses the company's GitHub App or a shared account. The two connections (company App for repos and PRs, personal account for Copilot only) are described in tech-stack. The spike shows which token type worked.
- [ ] The users and sign-in dependency is resolved in `roadmap.md`, and the handling of runs started by a webhook or schedule is stated.
- [ ] `mission.md`'s open question is closed or reworded, and "Bring your own model access" matches the verdict.
- [ ] `tech-stack.md`'s Copilot lines (agent runtime table, provider picker note, decisions log) say the same thing as the verdict.
- [ ] If the verdict is `no-go` for either mode, `roadmap.md` rows for 8.2 and 8.3 and the Milestone 8 text show the change, and `findings.md` names the fallback.

## Merge criteria
- [ ] All checks above pass in CI
- [ ] The owner has confirmed the terms reading in the PR (this is an engineering reading, not legal advice)
- [ ] `CHANGELOG.md` has an entry under `## [Unreleased]`
- [ ] No secrets in the spike, its output or the findings
- [ ] Spec changes are in the same PR as the findings, and no code and spec disagree
