# Fix: `openPR` fails with "transport 'file' not allowed"

Roadmap phase: 1.8 (fix)
Branch: fix/push-bundle-file-transport

## Context
After a "Generate docs" run is approved at its gate, the `publish` node fails:

```
tool_result  publish  Error executing tool openPR: git fetch failed: transport 'file' not allowed
```

`push_bundle` (`packages/github/src/agentic_github/push.py`) runs every git command with `protocol.allow=never` and `protocol.https.allow=always`. It enables `protocol.file.allow` only when the **remote** is `file://`. The writer's commits come in from a bundle file (`git fetch <work>/branch.bundle`), and git checks the `file` transport for a bundle path too. With a real `https://github.com/...` remote, that fetch is refused.

The 1.8 tests use a local bare repo as a `file://` remote. That enables the file transport for every command, so the tests never hit this path.

Principles that apply:
- **Humans approve irreversible actions (3):** the gate worked. The push after it must work too, or approvals do nothing.
- **Credentials stay inside the tool servers (tech stack):** the fix must not widen what the token-carrying git process can reach. The remote stays https only.
- **Small, verifiable steps (7):** a one-command change with a regression test.

## Scope
### In scope
- Allow the `file` transport only for the git command that fetches from the local bundle.
- A regression test that fails on `main` and passes after the fix.
- A CHANGELOG "Fixed" entry.

### Out of scope
- Changing which remotes `push_bundle` accepts (still `https://`, plus `file://` for tests).
- Restructuring `_Git`, or the test seam that hid the bug (could come later if it recurs).

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Where to allow `file` | Only on the bundle fetch, through a `_Git.fetch_bundle` method | Fetch and push to the remote keep the https-only lockdown from 1.8. |
| Test seam | Drive `_Git` with an `https://` remote URL, but run only local commands (no network) | Reproduces git's real refusal without a network call or an HTTP server. |
| Order | Test first, then the fix, then the changelog | The user chose this. It proves the test catches the bug. |

## Open questions
- None
