# Findings: Copilot SDK terms for hosted use

Read on 2026-11-18. This is an engineering reading of public pages, not legal advice. Quotes are short and verbatim. Where a page did not say, this file says "not addressed", never "allowed".

## Verdict

| Mode | Verdict | Why, in one line |
|---|---|---|
| Self-hosted (v1) | **Conditional go** | Official docs describe exactly this model: each user signs in with their own GitHub account, the app holds their token, usage is billed to that person. Conditions below. |
| Hosted multi-tenant (10.5) | **No-go until confirmed in writing** | The docs name SaaS as a fit, but no terms page addresses building a service for third parties on Copilot, and the Acceptable Use Policy bars reselling access. A written answer from GitHub is needed first. |

The spike was **not run** (no Copilot subscription or test credential was available in this session), so neither verdict is higher than conditional.

## Sources

| # | Source | Used for |
|---|---|---|
| S1 | https://docs.github.com/en/copilot/how-tos/copilot-sdk/auth/authenticate | Auth methods, token types, per-session tokens |
| S2 | https://docs.github.com/en/copilot/how-tos/copilot-sdk/set-up-copilot-sdk/github-oauth | Multi-user setup, billing, isolation |
| S3 | https://github.com/github/copilot-sdk (README, LICENSE) | Licence, status |
| S4 | https://pypi.org/project/github-copilot-sdk/ (1.0.34) | Python SDK, custom tools, status |
| S5 | https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features | Which terms govern Copilot |
| S6 | https://docs.github.com/en/site-policy/github-terms/github-terms-of-service | One login per person |
| S7 | https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies | Resale and automation |
| S8 | https://docs.github.com/en/site-policy/github-terms/github-pre-release-license-terms | What applies if the SDK is pre-release |
| S9 | https://github.com/customer-terms/github-generative-ai-services-terms | Volume-licence customers |

## Terms

- **The SDK itself is MIT** ("MIT License / Copyright GitHub, Inc.", S3). The README says Python downloads the runtime, and states no licence for it. **Unclear** whether the downloaded runtime has terms of its own.
- **No SDK-specific or Copilot CLI-specific terms were found** in S5 to S9. Copilot falls under the general terms: the Generative AI Services Terms for Business and Enterprise bought from GitHub, and "Section J (AI Features...)" of the Terms of Service for everyone else (S5).
- **One person per login.** "Your login may only be used by one person" (S6, B.3). A shared or pooled GitHub account for Copilot would break this. A per-person connection is consistent with it.
- **Resale.** "You will not ... sell, resell or exploit any portion of the Service, use of the Service, or access to the Service without our express written permission" (S7, section 6). Not limited to the API.
- **Automation.** The AUP bans "excessive automated bulk activity" (S7, section 4). Rate limits for Copilot are "subject to each user's Copilot rate limits" (S2). Abuse can lead to suspension of the account (S6, H and S7, 9 and 11).
- **Building on Copilot for third parties: not addressed** in any page read. The Actions and Codespaces sections bar commercial offerings of those services, but not Copilot.
- **Preview.** If the SDK counts as pre-release, S8 bars "any active production environment, including any use to process live customer data" and use "as a stand-alone offering or combine it with any of your applications for others to use". Whether it is pre-release is **unclear**: the README says it is generally available, the PyPI classifier says "3 - Alpha" (S3, S4). The README also says it "is becoming Microsoft Copilot SDK" with a `microsoft-copilot-sdk` package. We did not check which package is current.
- **Billing.** "Copilot usage is billed to each user's subscription" (S2). Where a person has seats from several organisations they must pick the billing entity, or premium requests are rejected (GitHub billing docs, from a search result only).

## Auth and technical feasibility

- **Per-person tokens work.** Supported: `gho_` OAuth user tokens, `ghu_` GitHub App user tokens, `github_pat_` fine-grained tokens. Not supported: `ghp_` classic tokens (S1, S2). **Not addressed:** `ghs_` GitHub App installation tokens, as used by our company App (1.5). Server-to-server auth exists as a separate method for organisation billing and was not read. So Copilot cannot be assumed to run on the company App's token, which matches the owner's requirement.
- **Multi-user pattern is documented.** "Each user authenticates with their own GitHub account." "One client per user (recommended) ... the strongest isolation." For one shared server, "set a token provider on each session", which is asked for `initial` and `refresh` tokens. "Production GitHub tokens typically last eight hours." The platform owns storage and refresh: "it doesn't manage the OAuth lifecycle" (S1, S2).
- **Flow.** The user authorises once through an OAuth or GitHub App flow (S2). The signed-in-user device flow is for the interactive CLI (S1). A worker uses the stored token, so no interactive login happens at run time.
- **Subscription.** "Each user needs an active Copilot subscription" (S2). BYOK needs none and is not what the owner asked for.
- **Custom tools exist** (`define_tool`, `tools=[...]` on a session, S4). This is what 8.2 needs to register the platform's tools.
- **Python.** 3.11 or newer, our floor is 3.12 (S4). Python SDK 1.0.34 at the time of reading.
- **Usage reporting: not found.** No usage event or premium-request field appeared in the text read. The only token counts seen were in compaction events. The normalised usage event (tech-stack, agent runtime) may not be fillable exactly. 8.2 must look for it first.
- **Permissions.** Without a handler, permission requests stay pending. `PermissionHandler.approve_all` exists. The platform's own gates and tool grants stay the safety layer (principle 3), so 8.2 must decide this explicitly.
- **Not read:** the "Backend services setup" and "Multi-tenancy and server deployments" pages, the server-to-server page, and the last part of the PyPI page. They may answer usage reporting and shared-server isolation.

## Per-person model and the platform

- The owner's model holds up: the company GitHub App stays for repos and PRs, and a user who wants Copilot adds a personal GitHub connection.
- A run must know whose Copilot it uses. With no users yet, the working assumption stands: the connection is stored in the workspace, labelled by GitHub login, and the person who starts a run picks one.
- **Runs with no person** (Jira 7.3, GitHub 7.6, schedules 18.1) have no one's subscription to use. Recommendation: they stay on Claude until a phase names an owner for a trigger. Using one person's token for a trigger firing from other people's events would run their entitlement for others, which S6 and S7 do not clearly allow.

## Conditions for the conditional go (self-hosted)

1. The owner confirms this reading of S5 to S7, or GitHub's answer says it is fine.
2. A run uses only its starter's token; no pooling, no shared account, never the company App's token.
3. Tokens are stored encrypted like other connections (1.4) and never appear in events or logs.
4. Pin the SDK version and re-read this file's sources if the package or licence changes (the Microsoft rename).
5. 8.2 starts by running the spike (`spike/`) with a real subscription, checking custom tools, usage fields and headless use, before building the adapter. If usage cannot be read, the phase's usage event is estimated and says so.

## Condition for hosted multi-tenant (10.5)

Ask GitHub in writing whether an operator may run Copilot, through the SDK and each customer's own user tokens, inside a service sold to other organisations. Until the answer is recorded, 10.5 does not offer Copilot.

## Spike

Not run. `spike/copilot_probe.py` is a ready-to-run script for 8.2's first task. It is untested: it follows the documented snippet in S4 and has never been executed.
