# Findings: Copilot SDK terms for hosted use

Read on 2026-11-18. This is an engineering reading of public pages, not legal advice. Quotes are short and verbatim. Where a page did not say, this file says "not addressed", never "allowed".

## Verdict

| Mode | Verdict | Why, in one line |
|---|---|---|
| Self-hosted (v1) | **Conditional go** | Official docs describe exactly this model: each user signs in with their own GitHub account, the app holds their token, usage is billed to that person. Conditions below. |
| Hosted multi-tenant (10.5) | **No-go until confirmed in writing** | The docs name SaaS as a fit, but no terms page addresses building a service for third parties on Copilot, and the Acceptable Use Policy bars reselling access. A written answer from GitHub is needed first. |

The spike was first not run (no subscription or credential). It was **run on 2026-11-22** (see "Spike results (8.2), online part"): per-person, headless use works, which meets condition 5 below. The verdicts stay conditional because the terms reading still needs the owner's confirmation (condition 1) and the SDK's pre-release status is unclear.

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

First written untested; run for real on 2026-11-22 (below). `spike/copilot_probe.py` is the script that ran.

## Spike results (8.2), offline part, 2026-11-18

Run without a token: the SDK was installed in a scratch virtualenv and its public API read (`inspect`) and compared with its documentation (Context7, `/github/copilot-sdk`, the repo's `docs/`). Nothing below was called against GitHub.

- **Package and status.** `github-copilot-sdk` 1.0.34 installs on our Python. Its PyPI classifier is still `3 - Alpha`, so the pre-release question (S8) stays open. The pinned version in 8.2 is 1.0.34 until the owner decides.
- **Per-person token.** `CopilotClient(github_token=…, use_logged_in_user=False)` is documented for a user token, and `create_session(github_token=…)` and `github_token_provider` exist for a token per session, which the multi-tenancy page recommends for a shared server.
- **Usage is reported.** `SessionEventType.ASSISTANT_USAGE` ("emitted once per model API call", with `model`, `input_tokens`, `output_tokens`, `cost`; input tokens already include cache reads and writes) and `SESSION_USAGE_INFO` exist. This corrects the first reading above ("usage reporting: not found"). What `cost` means (premium requests or money) is **not yet shown by a call**.
- **Tools.** `create_session(tools=[…])` takes custom tools; `available_tools` and `excluded_tools` can limit the SDK's built-in ones; `mcp_servers` exists too (a possible way to hand over the platform's MCP servers directly, to be compared with custom tools).
- **Permissions.** `on_permission_request` is a handler we write; `PermissionHandler.approve_all` is only a helper. Events `PERMISSION_REQUESTED` and `PERMISSION_COMPLETED` exist.
- **Streaming.** `streaming=True`, with `ASSISTANT_MESSAGE_DELTA`, `ASSISTANT_REASONING_DELTA`, `TOOL_EXECUTION_START` and `TOOL_EXECUTION_COMPLETE` events.
- **Still open after the offline part:** see the online part below, which closes most of it.

## Spike results (8.2), online part, 2026-11-22

Run with `spike/copilot_probe.py` in a scratch virtualenv (SDK 1.0.34, runtime 1.0.112 fetched by `python -m copilot download-runtime`), as one person's own GitHub account: `gh` was logged in as a user whose Copilot seat is a Business seat (`copilot_for_business_seat_quota`, assigned 2026-01-13). The token was the account's OAuth user token (`gho_`), read from the environment, never printed or stored.

- **Headless, per person: works.** `CopilotClient(github_token=…, use_logged_in_user=False)` ran a session with no signed-in user and no login prompt. The model was `claude-sonnet-5.5` served by Copilot (`provider: copilot`).
- **Custom tool: works.** `create_session(tools=[echo])`: the model called it with `{"text": "ping"}`, the SDK called our function, and the result `echo:ping` went back; the final answer was `done`. Calls arrive as `assistant.tool_call_delta`, `tool.execution_start`, `external_tool.requested` and `tool.execution_complete`.
- **Permission handler.** It was asked once, for the custom tool, with a `PermissionRequestCustomTool(tool_name, args, tool_call_id, tool_description)`. So the handler can answer from the node's grants (8.2 plan) and deny the rest.
- **Built-in tools off: partly shown.** With `available_tools=["echo"]` the session's tool definitions were 133 tokens and only `echo` was ever called; a run where the model is asked to use a built-in is still to do (8.2 adapter test).
- **Usage: reported, in AI credits, not premium requests.** `assistant.usage` (once per model call) carries `model`, `cache_read_tokens`, `cache_write_tokens`, an `ai_credits_status` and `copilot_usage.total_nano_aiu` with per-token-type `token_count`, `batch_size` and `cost_per_batch`. `session.usage_checkpoint` gives totals per model: `requests {cost 1.0, count 2}`, `input_tokens`, `output_tokens`, `reasoning_tokens` and `total_nano_aiu` (about 1.26 billion for this two-call run). The `cost` field of `assistant.usage` was not filled. So the adapter's normalised usage event takes tokens from the checkpoint or per-call events, and reports Copilot's own unit (AI credits) beside, not as, estimated USD; converting needs a price per credit, which the platform does not have.
- **Invalid token: fails clearly.** `session.create` fails with `Authentication failed: Failed to validate SDK token (401): GitHub returned: Bad credentials`, before any model call. That maps to the adapter's `copilot_needs_attention`.
- **Token in events: never.** The token string appeared in none of the events of either run.
- **Through our own adapter.** `CopilotRuntime` with the real `SdkConnector` (stub tool executor, tool `repo.read_file`, no writes) on the same account: the agent called the tool with `{"path": "README.md"}`, got the result, answered `Zephyr`, and the event stream was `usage, tool_call, tool_result, text_delta ×2, usage, message, completed`. Per-call usage was `input 3, output 21, cache write 5504`, then `input 3, output 6, cache read 5504, cache write 44`, so the connector's "input minus cache" arithmetic is right. `premium_requests` and `estimated_usd` stayed empty: Copilot reports AI credits, and the platform has no price for them.
- **Default model.** With no model set, the runtime's default ran as `gpt-6-luna`, not a Claude model. The account's model list is its own and per person, so 8.3's provider and capability checks cannot assume a model name.
- **Not run:** an expired (not invalid) token and a user with no subscription (no second account was available); the `github_token_provider` refresh path; a call from a worker process of ours.
