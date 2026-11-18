# Plan: Verify Copilot SDK terms for hosted multi-tenant use

## 1. Gather the sources
- [ ] Look up the Copilot SDK with `npx ctx7@latest library "GitHub Copilot SDK" "Python binding, authentication, custom tools, usage"`, then `docs` for the best match. Note the version, release status (preview or GA) and licence.
- [ ] Collect the primary sources, each with a URL and the date read: the SDK repository's licence, GitHub's Copilot product terms, any pre-release or additional-product terms, acceptable use policy, and the premium-request billing docs.
- [ ] Record any source that could not be read (login wall, removed page) instead of guessing its content.

## 2. Read the terms
- [ ] For each deployment mode, answer from the quoted clauses: may a service call the SDK with a user's entitlement? May one operator do so for several customers? May it be redistributed, wrapped or resold? Are there rate, automation or "agentic" restrictions?
- [ ] Answer the per-person question: may a server hold a user's OAuth token and run Copilot for that user in a worker? Does the terms' "per seat" wording forbid sharing or pooling? Which events (webhook, schedule) have no person?
- [ ] Write each answer as a short claim plus the clause that supports it. Mark anything the terms leave unclear as "unclear", never as allowed.

## 3. Spike (throwaway)
- [ ] Add `specs/2026-11-18-copilot-sdk-terms/spike/` with a single script and a `README` on how to run it. It reads the token from an environment variable, in its own virtual environment, outside the uv workspace.
- [ ] Authenticate as a person, with a user OAuth token (device flow or web flow), never a GitHub App installation token, and record whether Copilot accepts each.
- [ ] The script starts a headless session, registers one custom tool, makes one call that uses it, and prints the usage fields it receives (tokens, premium requests).
- [ ] Record what happened in `findings.md`: credential type that worked, whether any interactive login was needed, how the tool was registered, the usage shape. If there is no subscription, write "not run" and why.
- [ ] Check that no token appears in the script, its output or the log.

## 4. Write `findings.md`
- [ ] Sections: sources and dates, terms reading per deployment mode, auth and feasibility, spike result, unclear points, verdict per mode with conditions.
- [ ] If the verdict is `no-go` for a mode, add the fallback options and which roadmap phases change.

## 5. Record the decision in the specs
- [ ] `tech-stack.md`, decisions log: one row per deployment mode (self-hosted, hosted multi-tenant) with choice `go`, `conditional go` or `no-go` and its rationale, linking `findings.md`.
- [ ] `tech-stack.md`, agent runtime table and the lines it affects (the Copilot row's auth, the disabled-row note in "Start and settings"): match what the findings say.
- [ ] Resolve the per-person conflict: update the Copilot auth line in `tech-stack.md` (user OAuth, not the platform GitHub App), the mission's "chosen per workspace", and `roadmap.md` (a users phase before 8.2, or a per-user connection, as the findings recommend). 8.2 and 8.3 are re-scoped here if needed.
- [ ] `mission.md`: close the open question or reword it to what remains; update "Bring your own model access" if the verdict limits it.
- [ ] `roadmap.md`: change 8.2 and 8.3 only if the verdict requires it (conditions, order or dropped phase). The 8.1 status is marked by CI or the `complete-phase` skill, not by hand.
- [ ] `CHANGELOG.md`: an entry under `## [Unreleased]`.

## 6. Review and sign-off
- [ ] Re-read every quoted clause against its source for accuracy.
- [ ] Ask the owner to confirm the terms reading in the PR (see validation); open the PR with the `open-pr` skill.
