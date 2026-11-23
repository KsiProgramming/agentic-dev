"""Protected paths (13.5): what a writer can read but never change.

The platform's own list is always on, with no switch: only a workflow's `protect.allow` exempts a
node, and then a gate must follow it. A workflow adds its own patterns in `protect.paths`; the
files an earlier writer changed are frozen for a writer that `start_from` it (see `RunState`)."""

from collections.abc import Mapping, Sequence

from pydantic import JsonValue

from agentic_engine.gate import FileChange
from agentic_engine.spec.models import ProtectPolicy
from agentic_runtime import ProtectRule
from agentic_runtime.paths import first_match

MAX_FROZEN_SHOWN = 50
"""How many frozen files a writer is told by name; the rest are counted."""

PLATFORM_PROTECTED: tuple[tuple[str, str], ...] = (
    (".github/workflows/**", "CI: a writer that edits the pipeline decides what is checked"),
    (".github/actions/**", "CI: a composite action runs inside the pipeline"),
    ("**/.editorconfig", "analyzer config: it turns .NET and editor rules on and off"),
    ("**/.globalconfig", "analyzer config: it sets the severity of analyzer rules"),
    ("**/*.globalconfig", "analyzer config: it sets the severity of analyzer rules"),
    ("**/*.ruleset", "analyzer config: it sets the severity of .NET analyzer rules"),
    ("**/Directory.Build.props", "build config: it holds analyzer and warning settings"),
    ("**/Directory.Build.targets", "build config: it holds analyzer and warning settings"),
    ("**/ruff.toml", "analyzer config: it selects the Python lint rules"),
    ("**/.ruff.toml", "analyzer config: it selects the Python lint rules"),
    ("**/biome.json", "analyzer config: it selects the JavaScript lint rules"),
    ("**/biome.jsonc", "analyzer config: it selects the JavaScript lint rules"),
    ("**/.shellcheckrc", "analyzer config: it disables shell checks"),
    ("**/.gitleaks.toml", "scanner config: it sets what counts as a secret"),
    ("**/.gitleaksignore", "scanner config: it hides findings"),
)
"""The globs every writer is refused, each with why, in one place (shown wherever the rules are)."""

PLATFORM_GLOBS: tuple[str, ...] = tuple(glob for glob, _ in PLATFORM_PROTECTED)

ANALYZER_CONFIG_GLOBS: tuple[str, ...] = tuple(
    glob for glob, why in PLATFORM_PROTECTED if not why.startswith("CI")
)
"""The analyzer and scanner config among the defaults: what the evidence step reads from the
base (`scan.lint config: "base"`)."""


def platform_rule(path: str) -> str | None:
    """The platform default glob that protects `path`, or None."""
    return first_match(PLATFORM_GLOBS, path)


def static_rules(protect: ProtectPolicy | None) -> list[ProtectRule]:
    """The rules every writer is held to: the platform's list, then the workflow's `paths`."""
    rules = [ProtectRule(glob, "default") for glob in PLATFORM_GLOBS]
    if protect is not None:
        rules += [ProtectRule(glob, "workflow") for glob in protect.paths]
    return rules


def frozen_rules(saved: Mapping[str, JsonValue]) -> list[ProtectRule]:
    """The rules of the files a writer started from another's cannot change, from its `frozen`
    entry in the run's state."""
    files = saved.get("files")
    writer, gate = saved.get("writer"), saved.get("gate")
    return [
        ProtectRule(f, "frozen", writer=str(writer), gate=str(gate) if gate else None)
        for f in (files if isinstance(files, list) else [])
        if isinstance(f, str)
    ]


def mark_protected(
    changes: Sequence["FileChange"],
    state_frozen: Mapping[str, Mapping[str, JsonValue]],
    protect: ProtectPolicy | None,
) -> list["FileChange"]:
    """`changes` with each file that matches a protection rule marked (13.5): the platform's
    list and the workflow's patterns, and, for a writer that started from another's approved
    work, those files as frozen. A writer in `protect.allow` still shows a change to a path it was
    allowed as protected: a person approved it at a gate, and sees why."""
    rules = static_rules(protect)
    marked: list[FileChange] = []
    for change in changes:
        owner = change.node_id.partition(".")[0]
        own = rules + frozen_rules(state_frozen.get(owner, {}))
        found = next((r for r in own if r.kind == "frozen" and r.covers(change.path)), None)
        found = found or next((r for r in rules if r.covers(change.path)), None)
        marked.append(
            change.model_copy(update={"protected": True, "rule": found.kind})
            if found is not None
            else change
        )
    return marked


def folded_writers(
    ran: Sequence[str], state_frozen: Mapping[str, Mapping[str, JsonValue]]
) -> list[str]:
    """`ran` without the writers a later writer started from (13.5): their files are shown once,
    inside the later writer's diff, which is against the run's base and so holds them."""
    sources = {
        str(saved.get("writer"))
        for node, saved in state_frozen.items()
        if node in ran and saved.get("writer")
    }
    return [n for n in ran if n not in sources]


def protected_payload(
    rules: Sequence[ProtectRule], allow: Sequence[str] = ()
) -> dict[str, JsonValue]:
    """The `protected` a writer's `node_started` carries (13.5): the `patterns` (the platform's
    and the workflow's), the `frozen` files, and where they came from (`frozen_from`, `gate`)."""
    frozen = [r for r in rules if r.kind == "frozen"]
    payload: dict[str, JsonValue] = {
        "patterns": [r.glob for r in rules if r.kind != "frozen"],
        "frozen": [r.glob for r in frozen],
    }
    if frozen:
        payload["frozen_from"] = frozen[0].writer
        payload["gate"] = frozen[0].gate
    if allow:
        payload["allow"] = list(allow)
    return payload


def protected_text(rules: Sequence[ProtectRule], allow: Sequence[str] = ()) -> str:
    """The "# Protected paths" section every writer is told (13.5), after "# Work before you":
    the platform's list, the workflow's patterns and the files frozen at a gate. Written from the
    spec and the run's state, never from model output; the frozen files are capped."""
    defaults = [r.glob for r in rules if r.kind == "default"]
    workflow = [r.glob for r in rules if r.kind == "workflow"]
    frozen = [r for r in rules if r.kind == "frozen"]
    lines = [
        "# Protected paths",
        "",
        "You can read these paths but not change them: a write to one is refused, the attempt is "
        "counted and shown to the person who reviews your work. If one must change, say so in "
        "your answer.",
        "",
        "- By the platform (CI and analyzer config): " + ", ".join(f"`{g}`" for g in defaults),
    ]
    if workflow:
        lines.append("- By this workflow: " + ", ".join(f"`{g}`" for g in workflow))
    if frozen:
        first = frozen[0]
        shown = frozen[:MAX_FROZEN_SHOWN]
        more = len(frozen) - len(shown)
        files = ", ".join(f"`{r.glob}`" for r in shown) + (f" and {more} more" if more else "")
        lines.append(
            f"- Approved at `{first.gate}` from `{first.writer}`, on your branch already: {files}"
        )
    if allow:
        lines.append("- You may change: " + ", ".join(f"`{g}`" for g in allow))
    return "\n".join(lines)
